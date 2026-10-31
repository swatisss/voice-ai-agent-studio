"""Database engine, sessions and portable column types.

Spec: /data/data-model.md (DM-01), /decisions/adr-0004-storage-and-vectors.md
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from voiceai.config import get_settings


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, returns timezone-aware UTC on every backend."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):  # noqa: ANN001
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(url: str | None = None) -> AsyncEngine:
    """(Re)create the engine; tests call this with a temp database URL."""
    global _engine, _sessionmaker
    url = url or get_settings().database_url
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    _engine = create_async_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def engine() -> AsyncEngine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def init_db(drop: bool = False) -> None:
    from voiceai import models  # noqa: F401  (register tables)

    async with engine().begin() as conn:
        if drop:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        missing = await conn.run_sync(_add_missing_columns)
        relax = await conn.run_sync(_not_null_to_relax)
        if relax and conn.dialect.name != "sqlite":
            for table, column in relax:
                await conn.exec_driver_sql(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
    if relax and engine().dialect.name == "sqlite":
        await _sqlite_rebuild(sorted({table for table, _ in relax}))
    if missing or relax:
        import logging

        logging.getLogger("voiceai.db").info("schema upgraded: added %s, relaxed %s", missing, relax)


def _column_default(col) -> object:  # noqa: ANN001
    """The Python default of a model column as a SQL literal value (callables such as `list` are called)."""
    if col.default is None:
        return None
    arg = col.default.arg
    if callable(arg):
        try:
            arg = arg(None)
        except TypeError:
            arg = arg()
    return arg if isinstance(arg, str | int | float | bool | list | dict) else None  # timestamps stay NULL


def _add_missing_columns(sync_conn) -> list[str]:  # noqa: ANN001
    """DM-01: columns added to an existing table by a later CP are added on start, filled with the model default."""
    import json

    from sqlalchemy import inspect

    insp = inspect(sync_conn)
    existing = set(insp.get_table_names())
    added = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = col.type.compile(dialect=sync_conn.dialect)
            value = _column_default(col)
            sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'
            if value is not None:
                literal = json.dumps(value) if isinstance(value, list | dict) else (int(value) if isinstance(value, bool) else value)
                sql += " DEFAULT " + (f"'{literal}'" if isinstance(literal, str) else str(literal))
            sync_conn.exec_driver_sql(sql)
            added.append(f"{table.name}.{col.name}")
    return added


def _not_null_to_relax(sync_conn) -> list[tuple[str, str]]:  # noqa: ANN001
    """Columns a later CP made nullable that an existing database still declares NOT NULL."""
    from sqlalchemy import inspect

    insp = inspect(sync_conn)
    existing = set(insp.get_table_names())
    out = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        db_cols = {c["name"]: c for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.nullable and not col.primary_key and col.name in db_cols and not db_cols[col.name]["nullable"]:
                out.append((table.name, col.name))
    return out


async def _sqlite_rebuild(tables: list[str]) -> None:
    """SQLite cannot drop NOT NULL: recreate the table from the model and copy its rows, with foreign keys off so
    rows that reference it (e.g. eval_results -> eval_runs) are neither cascaded nor re-pointed."""
    async with engine().connect() as raw:
        conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        try:
            for name in tables:
                table = Base.metadata.tables[name]
                old = f"{name}__old"
                await conn.exec_driver_sql("BEGIN")
                await conn.exec_driver_sql(f'ALTER TABLE "{name}" RENAME TO "{old}"')
                rows = (await conn.exec_driver_sql(
                    f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{old}' AND sql IS NOT NULL")).all()
                for (index,) in rows:
                    await conn.exec_driver_sql(f'DROP INDEX "{index}"')
                await conn.run_sync(lambda c: table.create(c))
                cols = ", ".join(f'"{c.name}"' for c in table.columns)
                await conn.exec_driver_sql(f'INSERT INTO "{name}" ({cols}) SELECT {cols} FROM "{old}"')
                await conn.exec_driver_sql(f'DROP TABLE "{old}"')
                await conn.exec_driver_sql("COMMIT")
        finally:
            await conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
