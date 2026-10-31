"""Schema upgrade on start for columns added by later CPs.

Covers: DM-01
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from voiceai import db


async def test_old_eval_tables_are_upgraded(tmp_path: Path):
    """An eval_runs table from before CP-0021 (NOT NULL proposal_id) gains the new columns, keeps its rows and the
    results that reference it, and accepts a suite run without a proposal."""
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql(
            "CREATE TABLE eval_runs (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), agent_id VARCHAR(32), "
            "proposal_id VARCHAR(32) NOT NULL, baseline_version_id VARCHAR(32) NOT NULL, status VARCHAR(16), summary JSON, error TEXT, "
            "created_at DATETIME NOT NULL, finished_at DATETIME)")
        await conn.exec_driver_sql("CREATE INDEX ix_eval_runs_proposal_id ON eval_runs (proposal_id)")
        await conn.exec_driver_sql(
            "CREATE TABLE eval_results (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), "
            "eval_run_id VARCHAR(32) REFERENCES eval_runs(id) ON DELETE CASCADE, case_key VARCHAR(120), case_type VARCHAR(16), arm VARCHAR(16), "
            "call_id VARCHAR(32), expected VARCHAR(16), passed BOOLEAN, judge JSON, created_at DATETIME NOT NULL)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO eval_runs VALUES ('r1', 't', 'a', 'p1', 'v1', 'done', '{}', NULL, '2026-10-01 00:00:00', NULL)")
        await conn.exec_driver_sql("INSERT INTO eval_results VALUES ('x1', 't', 'r1', 'k', 'regression', 'candidate', NULL, 'resolved', 1, '{}', '2026-10-01 00:00:00')")
    await db.init_db()
    async with db.engine().begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"]: x for x in inspect(c).get_columns("eval_runs")})
        assert cols["proposal_id"]["nullable"] and cols["baseline_version_id"]["nullable"]
        assert {"kind", "target", "config", "repeats", "trigger", "scenario_ids"} <= set(cols)
        assert (await conn.execute(text("SELECT kind, repeats, proposal_id FROM eval_runs"))).one() == ("proposal", 1, "p1")
        assert (await conn.execute(text("SELECT repeat, failures, eval_run_id FROM eval_results"))).one() == (1, "[]", "r1")
        await conn.execute(text("INSERT INTO eval_runs (id, tenant_id, agent_id, kind, status, summary, created_at, repeats, trigger, scenario_ids) "
                                "VALUES ('r2', 't', 'a', 'suite', 'running', '{}', '2026-10-31 00:00:00', 3, 'manual', '[]')"))
    await db.engine().dispose()
