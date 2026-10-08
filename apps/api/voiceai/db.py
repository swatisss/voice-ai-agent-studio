"""Database engine, sessions and portable column types.

Spec: /data/data-model.md, /decisions/adr-0004-storage-and-vectors.md
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from sqlalchemy import DateTime, event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from voiceai.config import get_settings

T = TypeVar("T")


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


async def get_owned(session: AsyncSession, model: type[T], tenant_id: str, row_id: str) -> T | None:
    """One tenant-owned row, or None when this tenant does not own it (MT-05).

    Every repository helper for a tenant-owned table goes through here, so the `tenant_id`
    predicate can never be forgotten and another tenant's id is indistinguishable from a
    missing one (/architecture/multi-tenancy.md).
    """
    return await session.scalar(select(model).where(model.id == row_id, model.tenant_id == tenant_id))


async def init_db(drop: bool = False) -> None:
    from voiceai import models  # noqa: F401  (register tables)

    async with engine().begin() as conn:
        if drop:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
