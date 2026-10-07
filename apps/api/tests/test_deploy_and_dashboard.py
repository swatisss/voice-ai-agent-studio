"""Single-origin web serving, health, and dashboard metrics. Covers: DEP-01, DEP-02, UI-03"""
from __future__ import annotations

from starlette.testclient import TestClient


def test_static_web_and_api_404(tmp_path, monkeypatch):
    """Covers: DEP-01, DEP-02"""
    web = tmp_path / "out"
    (web / "agents").mkdir(parents=True)
    (web / "index.html").write_text("<html>home</html>")
    (web / "agents" / "index.html").write_text("<html>agents</html>")
    monkeypatch.setenv("WEB_DIST_DIR", str(web))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'web.db').as_posix()}")
    monkeypatch.setenv("AUTO_SEED", "1")
    from voiceai.config import get_settings

    get_settings.cache_clear()
    from voiceai.main import create_app

    with TestClient(create_app()) as c:
        assert "home" in c.get("/").text
        assert "agents" in c.get("/agents/").text
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json()["error"] == "not_found"
        health = c.get("/healthz").json()
        assert health["status"] == "ok" and health["db"] is True
        assert len(c.get("/api/tenants").json()["items"]) == 2
    get_settings.cache_clear()


def test_next_segment_mapping():
    """Covers: DEP-02"""
    from voiceai.main import next_segment_path

    assert next_segment_path("insights/__next.insights.__PAGE__.txt") == "insights/__next.insights/__PAGE__.txt"
    assert next_segment_path("insights/cluster/__next.insights.cluster.__PAGE__.txt") == "insights/cluster/__next.insights/cluster/__PAGE__.txt"
    assert next_segment_path("__next._tree.txt") is None
    assert next_segment_path("agents/index.html") is None


async def test_containment_rate(client, seeded):
    """Covers: UI-03"""
    t = (await client.get("/api/dashboard/summary", headers={"X-Tenant-Id": "evergreen-care"})).json()["totals"]
    assert t["calls"] == 123 and t["resolved"] == 82 and t["escalated"] == 38 and t["abandoned"] == 3
    assert t["containment_rate"] == round(82 / 120, 4)
