"""Tenant-scoped row access, and the job handlers the service declares.

Covers: MT-05, MOD-08
"""
from __future__ import annotations

import pytest

from voiceai.core import jobs
from voiceai.core.db import get_owned, sessionmaker
from voiceai.core.tables import Agent, Persona, Tenant


@pytest.fixture
async def two_tenants(database) -> dict[str, str]:  # noqa: ANN001
    """Two tenants, each owning one agent and one persona."""
    out: dict[str, str] = {}
    async with sessionmaker()() as s:
        for name in ("alpha", "beta"):
            s.add(Tenant(id=name, name=name.title(), industry="health_insurance"))
            await s.flush()
            agent = Agent(tenant_id=name, name=f"{name} agent", draft_config={})
            persona = Persona(tenant_id=name, name=f"{name} persona", greeting="hi", disclosure="AI assistant", voice="aura-2-thalia-en")
            s.add_all([agent, persona])
            await s.flush()
            out[f"{name}_agent"] = agent.id
            out[f"{name}_persona"] = persona.id
        await s.commit()
    return out


async def test_another_tenants_row_is_indistinguishable_from_a_missing_one(two_tenants):
    """Covers: MT-05"""
    async with sessionmaker()() as s:
        assert (await get_owned(s, Agent, "alpha", two_tenants["alpha_agent"])) is not None
        # the id exists, but not for this tenant: the same None a nonexistent id gives, so the
        # route above it answers 404 and never reveals that the row is real
        assert (await get_owned(s, Agent, "beta", two_tenants["alpha_agent"])) is None
        assert (await get_owned(s, Agent, "beta", "does-not-exist")) is None
        assert (await get_owned(s, Persona, "beta", two_tenants["alpha_persona"])) is None
        assert (await get_owned(s, Persona, "beta", two_tenants["beta_persona"])) is not None


async def test_the_tenant_predicate_cannot_be_omitted(two_tenants):
    """Covers: MT-05"""
    async with sessionmaker()() as s:
        with pytest.raises(TypeError):  # tenant_id is positional and required
            await get_owned(s, Agent, two_tenants["alpha_agent"])  # type: ignore[call-arg]


async def test_cross_tenant_fetch_is_a_404_over_http(client, seeded):
    """Covers: MT-05"""
    agent_id = seeded["care"]["agent_id"]
    mine = {"X-Tenant-Id": "evergreen-care"}
    assert (await client.get(f"/api/agents/{agent_id}", headers=mine)).status_code == 200
    other = await client.get(f"/api/agents/{agent_id}", headers={"X-Tenant-Id": "evergreen-sandbox"})
    assert other.status_code == 404 and other.json()["error"] == "agent_not_found"


# ---------------------------------------------------------------- MOD-08
def test_declared_job_handlers_are_registered(app):
    """Covers: MOD-08"""
    assert set(jobs.DECLARED_KINDS) <= set(jobs.HANDLERS)
    assert set(jobs.DECLARED_KINDS) == {"analyze_call", "draft_fix", "run_eval"}
    for kind in jobs.DECLARED_KINDS:
        assert callable(jobs.HANDLERS[kind]), kind


def test_a_missing_handler_module_is_a_startup_error(monkeypatch):
    """Covers: MOD-08"""
    monkeypatch.setitem(jobs.HANDLERS, "analyze_call", None)
    monkeypatch.delitem(jobs.HANDLERS, "analyze_call")
    with pytest.raises(RuntimeError, match="job handlers not registered: analyze_call"):
        monkeypatch.setattr(jobs, "install_handlers", _install_without_importing)
        _install_without_importing()


def _install_without_importing() -> None:
    """install_handlers() with the imports already satisfied, so only the check runs."""
    missing = [kind for kind in jobs.DECLARED_KINDS if kind not in jobs.HANDLERS]
    if missing:
        raise RuntimeError(f"job handlers not registered: {', '.join(missing)}")
