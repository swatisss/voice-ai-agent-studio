"""scripts/phone_demo.py: pre-flight, tunnel discovery, Twilio webhook, number mapping and the orchestration, against local fakes.

Covers: DEV-07, DEV-08, DEV-09, DEV-10
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load():  # noqa: ANN202
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("phone_demo", REPO / "scripts" / "phone_demo.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


demo = _load()
FULL = {
    "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "secret-token-value", "TWILIO_PHONE_NUMBER": "+15551234567",
    "OPENAI_API_KEY": "sk-secret-key-value",
}


def args(**over):  # noqa: ANN003, ANN202
    return argparse.Namespace(**{"port": 8000, "public_url": None, "keep_webhook": False, "check": False, **over})


def which_none(_: str) -> None:
    return None


def test_preflight_names_each_problem_and_never_prints_keys():
    """Covers: DEV-07"""
    cfg = {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_PHONE_NUMBER": "555-1234", "DEMO_TRANSFER_TO": "0123"}
    problems = demo.preflight(cfg, args(), which=which_none, uv=["uv"], in_use=lambda p: True)
    text = "\n".join(problems)
    for expected in ("TWILIO_AUTH_TOKEN is missing", "OPENAI_API_KEY is missing", "international format", "DEMO_TRANSFER_TO", "no tunnel tool", "port 8000 is busy"):
        assert expected in text, expected
    assert "ACtest" not in text and "TWILIO_ACCOUNT_SID" not in text
    assert demo.preflight({**FULL, "TWILIO_AUTH_TOKEN": "secret-token-value"}, args(), which=which_none, uv=["uv"], in_use=lambda p: False) != []
    assert demo.preflight(FULL, args(), which=lambda n: "/bin/ngrok", uv=["uv"], in_use=lambda p: False) == []
    assert demo.preflight(FULL, args(public_url="https://x.example"), which=which_none, uv=["uv"], in_use=lambda p: False) == []
    assert any("uv is not installed" in p for p in demo.preflight(FULL, args(public_url="https://x"), which=which_none, uv=[], in_use=lambda p: False))


def test_check_starts_nothing_and_touches_no_network(monkeypatch, capsys):
    """Covers: DEV-07"""
    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("--check must not start a process or open a connection")

    monkeypatch.setattr(demo, "load_config", lambda: dict(FULL))
    monkeypatch.setattr(demo.shutil, "which", lambda n: "/bin/ngrok" if n == "ngrok" else None)
    monkeypatch.setattr(demo.dev, "uv_command", lambda: ["uv"])
    monkeypatch.setattr(demo.dev, "port_in_use", lambda p: False)
    monkeypatch.setattr(demo.subprocess, "Popen", boom)
    monkeypatch.setattr(demo.urllib.request, "urlopen", boom)
    assert demo.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "everything is in place" in out and "sk-secret-key-value" not in out and "secret-token-value" not in out
    monkeypatch.setattr(demo, "load_config", lambda: {})
    assert demo.main(["--check"]) == 2


def test_tunnel_urls_are_found():
    """Covers: DEV-08"""
    listing = {"tunnels": [{"public_url": "http://abc.ngrok.app"}, {"public_url": "https://abc.ngrok.app"}]}
    assert demo.pick_ngrok_url(listing) == "https://abc.ngrok.app" and demo.pick_ngrok_url({"tunnels": []}) is None
    line = "2026-10-16T10:00:00Z INF |  https://quiet-river-abc.trycloudflare.com  |"
    assert demo.parse_cloudflared_url(line) == "https://quiet-river-abc.trycloudflare.com"
    assert demo.parse_cloudflared_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None


class FakeTwilio(BaseHTTPRequestHandler):
    numbers = {"+15551234567": {"sid": "PN1", "voice_url": "https://old.example/voice"}}
    updates: list = []

    def log_message(self, *a):  # noqa: ANN002, ANN202
        pass

    def _send(self, body: dict, status: int = 200) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: ANN202, N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        row = self.numbers.get(query.get("PhoneNumber", [""])[0])
        self._send({"incoming_phone_numbers": [{"sid": row["sid"], "voice_url": row["voice_url"]}] if row else []})

    def do_POST(self):  # noqa: ANN202, N802
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.updates.append((self.path, self.headers["Authorization"][:6], {k: v[0] for k, v in form.items()}))
        self._send({})


@pytest.fixture
def twilio():  # noqa: ANN201
    FakeTwilio.updates = []
    server = HTTPServer(("127.0.0.1", 0), FakeTwilio)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {**FULL, "TWILIO_API_BASE": f"http://127.0.0.1:{server.server_port}"}
    server.shutdown()


def test_webhook_is_set_and_restored(twilio):
    """Covers: DEV-09"""
    sid, previous = demo.set_webhook(twilio, "https://abc.ngrok.app/api/telephony/twilio/voice")
    assert (sid, previous) == ("PN1", "https://old.example/voice")
    path, auth, form = FakeTwilio.updates[-1]
    assert path == "/2010-04-01/Accounts/ACtest/IncomingPhoneNumbers/PN1.json" and auth == "Basic "
    assert form == {"VoiceUrl": "https://abc.ngrok.app/api/telephony/twilio/voice", "VoiceMethod": "POST"}
    demo.restore_webhook(twilio, sid, previous)
    assert FakeTwilio.updates[-1][2]["VoiceUrl"] == "https://old.example/voice"
    with pytest.raises(demo.DemoError, match=r"\+15559990000"):
        demo.set_webhook({**twilio, "TWILIO_PHONE_NUMBER": "+15559990000"}, "https://x/voice")


class FakeApi:
    """The three endpoints setup_agent uses, in memory."""

    def __init__(self, mapped_to: str | None = None, published: bool = True) -> None:
        self.agents = [{"id": "a1", "name": "Insurance Claims Agent", "published_version": {"version": 1} if published else None},
                       {"id": "a2", "name": "Customer Care Agent", "published_version": {"version": 1}}]
        self.numbers = [{"id": "n1", "e164": "+15551234567", "agent_id": mapped_to}] if mapped_to else []
        self.draft = {"telephony": {"transfer_to": None}}
        self.log: list[str] = []

    def __call__(self, method: str, path: str, body=None):  # noqa: ANN001, ANN204
        self.log.append(f"{method} {path}")
        if (method, path) == ("GET", "/api/agents"):
            return 200, {"items": self.agents}
        if (method, path) == ("GET", "/api/phone-numbers"):
            return 200, {"items": self.numbers}
        if method == "DELETE":
            self.numbers = [n for n in self.numbers if n["id"] != path.rsplit("/", 1)[1]]
            return 204, None
        if (method, path) == ("POST", "/api/phone-numbers"):
            self.numbers.append({"id": "n2", "e164": body["e164"], "agent_id": body["agent_id"]})
            return 200, {}
        if (method, path) == ("GET", "/api/agents/a1"):
            return 200, {"draft_config": json.loads(json.dumps(self.draft))}
        if (method, path) == ("PUT", "/api/agents/a1"):
            self.draft = body["draft_config"]
            return 200, {}
        if (method, path) == ("POST", "/api/agents/a1/publish"):
            return 200, {}
        return 404, {"detail": "unexpected " + path}


def test_mapping_is_idempotent():
    """Covers: DEV-10"""
    api = FakeApi()
    assert demo.setup_agent(api, "Insurance Claims Agent", "+15551234567") == ["+15551234567 -> Insurance Claims Agent"]
    assert api.numbers[0]["agent_id"] == "a1"
    assert demo.setup_agent(api, "Insurance Claims Agent", "+15551234567") == []  # nothing left to do
    other = FakeApi(mapped_to="a2")
    done = demo.setup_agent(other, "Insurance Claims Agent", "+15551234567")
    assert other.numbers[0]["agent_id"] == "a1" and any("re-mapped" in d for d in done)

    api = FakeApi(mapped_to="a1")
    done = demo.setup_agent(api, "Insurance Claims Agent", "+15551234567", "+15557654321")
    assert done == ["transfer number +15557654321 saved and published"] and api.draft["telephony"]["transfer_to"] == "+15557654321"
    api.log.clear()
    assert demo.setup_agent(api, "Insurance Claims Agent", "+15551234567", "+15557654321") == []
    assert not any(c.startswith(("PUT", "POST")) for c in api.log)  # equal already: no second publish

    with pytest.raises(demo.DemoError, match="Mortgage Agent.*Customer Care Agent"):
        demo.setup_agent(FakeApi(), "Mortgage Agent", "+15551234567")
    with pytest.raises(demo.DemoError, match="not published"):
        demo.setup_agent(FakeApi(published=False), "Insurance Claims Agent", "+15551234567")


class FakeProc:
    def __init__(self, env=None):  # noqa: ANN001
        self.env = env
        self.pid = 1

    def poll(self):  # noqa: ANN202
        return None

    def wait(self, timeout=None):  # noqa: ANN001, ANN202
        return 0


def test_run_gives_the_api_the_tunnel_url_and_restores_on_exit(monkeypatch, capsys):
    """Covers: DEV-08, DEV-09"""
    started, killed, hooks = [], [], []
    api = FakeApi()

    def popen(cmd, **kw):  # noqa: ANN001, ANN003, ANN202
        started.append((cmd, kw.get("env") or {}))
        return FakeProc()

    def sleeper(_: float) -> None:
        raise KeyboardInterrupt  # Ctrl+C after the first poll

    monkeypatch.setattr(demo, "load_config", lambda: {**FULL, "PUBLIC_BASE_URL": "https://stale.example"})
    monkeypatch.setattr(demo.shutil, "which", lambda n: "/bin/ngrok" if n == "ngrok" else None)
    monkeypatch.setattr(demo.dev, "uv_command", lambda: ["uv"])
    monkeypatch.setattr(demo.dev, "port_in_use", lambda p: False)
    monkeypatch.setattr(demo.dev, "kill_tree", lambda proc: killed.append(proc))
    monkeypatch.setattr(demo, "start_tunnel", lambda port, cfg: (FakeProc(), "https://fresh.ngrok.app"))
    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo, "wait_for", lambda url, proc: None)
    monkeypatch.setattr(demo, "http_request", lambda base: api)
    monkeypatch.setattr(demo, "set_webhook", lambda cfg, url: (hooks.append(("set", url)) or ("PN1", "https://old.example/voice")))
    monkeypatch.setattr(demo, "restore_webhook", lambda cfg, sid, prev: hooks.append(("restore", prev)))
    monkeypatch.setattr(demo.time, "sleep", sleeper)
    assert demo.main([]) == 0
    (cmd, env), = started
    assert cmd[-3:] == ["serve", "--port", "8000"] and env["PUBLIC_BASE_URL"] == "https://fresh.ngrok.app"  # not the stale .env value
    assert hooks == [("set", "https://fresh.ngrok.app/api/telephony/twilio/voice"), ("restore", "https://old.example/voice")]
    assert len(killed) == 2  # the API and the tunnel
    assert "READY - call +15551234567" in capsys.readouterr().out

    hooks.clear()
    started.clear()
    killed.clear()
    monkeypatch.setattr(demo, "start_tunnel", lambda *a: (_ for _ in ()).throw(AssertionError("no tunnel with --public-url")))
    monkeypatch.setattr(demo.shutil, "which", lambda n: None)
    assert demo.main(["--public-url", "https://cloud.run.app/", "--keep-webhook"]) == 0
    assert started[0][1]["PUBLIC_BASE_URL"] == "https://cloud.run.app" and hooks == [("set", "https://cloud.run.app/api/telephony/twilio/voice")]
