"""scripts/dev.py: plan building, pre-flight, prefixed output and process-tree shutdown.

Covers: DEV-01, DEV-02, DEV-03, DEV-04, DEV-05, DEV-06, DEV-12, DEV-13, DEV-14, DEV-18, DEV-19, DEV-20, DEV-21, DEV-22, DEV-23
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PY = sys.executable


def _load():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("dev_launcher", REPO / "scripts" / "dev.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass resolves string annotations through sys.modules
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


dev = _load()


def ns(**kw) -> argparse.Namespace:  # noqa: ANN003
    base = dict(single_origin=False, skip_build=False, api_port=8000, web_port=3000, no_reload=False, fake=False, install=False, check=False,
                no_chat=True, no_login=True, reset=False, no_reseed=True)  # the older tests opt out of the CP-0053 defaults
    return argparse.Namespace(**{**base, **kw})


def _repo(tmp: Path, venv: bool = True, node_modules: bool = True, out: bool = False) -> Path:
    (tmp / "apps" / "api").mkdir(parents=True)
    (tmp / "apps" / "web").mkdir(parents=True)
    if venv:
        (tmp / "apps" / "api" / ".venv").mkdir()
    if node_modules:
        (tmp / "apps" / "web" / "node_modules").mkdir()
    if out:
        (tmp / "apps" / "web" / "out").mkdir()
    return tmp


# ---------------------------------------------------------------- plan
def test_dev_mode_plan_wires_cors_and_api_base():
    """Covers: DEV-01"""
    plan = dev.make_plan(ns(web_port=3100, api_port=8123), ["uv"], "npm", environ={})
    api, web = plan.services[:2]
    assert api.name == "api" and web.name == "web" and plan.pre == []
    assert api.cmd == ["uv", "run", "voiceai", "serve", "--port", "8123", "--reload"]
    assert "http://localhost:3100" in api.env["CORS_ORIGINS"]
    assert web.cmd == ["npm", "run", "dev", "--", "-p", "3100"]
    assert web.env["NEXT_PUBLIC_API_BASE"] == "http://localhost:8123"
    assert plan.open_url == "http://localhost:3100"
    assert "--reload" not in dev.make_plan(ns(no_reload=True), ["uv"], "npm", environ={}).services[0].cmd


def test_single_origin_plan_builds_then_serves_api_only():
    """Covers: DEV-02"""
    plan = dev.make_plan(ns(single_origin=True), ["uv"], "npm", environ={})
    assert [s.name for s in plan.pre] == ["web"] and plan.pre[0].cmd == ["npm", "run", "build"]
    assert plan.pre[0].env["NEXT_PUBLIC_API_BASE"] == ""
    assert [s.name for s in plan.services] == ["api", "mock"] and "--reload" not in plan.services[0].cmd
    assert plan.open_url == "http://localhost:8000"
    assert dev.make_plan(ns(single_origin=True, skip_build=True), ["uv"], "npm", environ={}).pre == []


def test_chat_is_on_by_default_and_runs_in_parallel(tmp_path):
    """Covers: DEV-18"""
    (tmp_path / "node_modules").mkdir()
    plan = dev.make_plan(ns(no_chat=False), ["uv"], "npm", environ={}, dotenv={}, chat_dir=tmp_path)
    assert [s.name for s in plan.services][:3] == ["api", "web", "mock"] and plan.services[-1].name == "chat"
    chat = plan.services[-1]
    assert chat.cmd == ["npm", "run", "dev", "--", "-p", "3100"]
    assert chat.env["VOICEAI_API_URL"] == "http://localhost:8000" and plan.ready["chat"] == "http://localhost:3100/"
    custom = dev.make_plan(ns(no_chat=False, chat_port=3200, single_origin=True, skip_build=True), ["uv"], "npm", environ={}, dotenv={}, chat_dir=tmp_path)
    assert custom.services[-1].cmd[-1] == "3200"
    assert "chat" not in [s.name for s in dev.make_plan(ns(no_chat=True), ["uv"], "npm", environ={}, dotenv={}).services]


def test_chat_preflight_reports_a_busy_port_only(tmp_path):
    """Covers: DEV-18"""
    repo = _repo(tmp_path)
    errors, _, _ = dev.preflight(ns(no_chat=False), ["uv"], "npm", environ={}, root=repo, in_use=lambda p: p == 3100, health=lambda p: True)
    assert any("3100" in e and "--chat-port" in e for e in errors)
    errors, _, _ = dev.preflight(ns(no_chat=False), ["uv"], "npm", environ={}, root=repo, in_use=lambda p: False, health=lambda p: True)
    assert not any("chat" in e for e in errors)  # missing chat dependencies are installed by the plan, not an error (DEV-20)
    errors, _, _ = dev.preflight(ns(no_chat=True), ["uv"], "npm", environ={}, root=repo, in_use=lambda p: p == 3100, health=lambda p: True)
    assert not any("3100" in e for e in errors)


def test_demo_passwords_only_when_none_is_set():
    """Covers: DEV-19"""
    names = ["STUDIO_ADMIN_PASSWORD", "STUDIO_REVIEWER_PASSWORD", "STUDIO_SPECIALIST_PASSWORD"]
    plan = dev.make_plan(ns(no_login=False), ["uv"], "npm", environ={}, dotenv={})
    api = plan.services[0]
    assert [api.env[n] for n in names] == ["admin-demo-pass", "reviewer-demo-pass", "specialist-demo-pass"] and plan.applied_logins
    empty = dev.make_plan(ns(no_login=False), ["uv"], "npm", environ={}, dotenv={n: "" for n in names})  # `.env.example` leaves them empty
    assert empty.services[0].env["STUDIO_ADMIN_PASSWORD"] == "admin-demo-pass"
    for environ, dotenv in (({"STUDIO_REVIEWER_PASSWORD": "mine"}, {}), ({}, {"STUDIO_SPECIALIST_PASSWORD": "mine"})):
        own = dev.make_plan(ns(no_login=False), ["uv"], "npm", environ=environ, dotenv=dotenv)
        assert not any(n in own.services[0].env for n in names) and own.applied_logins == {}  # yours is never replaced, none added
    off = dev.make_plan(ns(no_login=True), ["uv"], "npm", environ={}, dotenv={})
    assert not any(n in off.services[0].env for n in names)


def test_chat_install_step_only_when_dependencies_are_missing(tmp_path):
    """Covers: DEV-20"""
    plan = dev.make_plan(ns(no_chat=False), ["uv"], "npm", environ={}, dotenv={}, chat_dir=tmp_path)
    assert [s.name for s in plan.pre] == ["chat-install"] and plan.pre[0].cmd[:2] == ["npm", "install"] and plan.pre[0].cwd == tmp_path
    (tmp_path / "node_modules").mkdir()
    assert dev.make_plan(ns(no_chat=False), ["uv"], "npm", environ={}, dotenv={}, chat_dir=tmp_path).pre == []
    assert dev.make_plan(ns(no_chat=True), ["uv"], "npm", environ={}, dotenv={}, chat_dir=tmp_path / "none").pre == []


def _api_dir(tmp: Path) -> Path:
    api = tmp / "apps" / "api"
    (api / "voiceai" / "seed").mkdir(parents=True)
    (api / "voiceai" / "seed" / "loader.py").write_text("SEED = 1\n", encoding="utf-8")
    (tmp / "specs" / "demo-data").mkdir(parents=True)
    (tmp / "specs" / "demo-data" / "members.md").write_text("Sarah\n", encoding="utf-8")
    return api


def test_seed_step_follows_the_stamp(tmp_path):
    """Covers: DEV-21"""
    api = _api_dir(tmp_path)
    args = ns(no_reseed=False)
    first = dev.make_plan(args, ["uv"], "npm", environ={}, dotenv={}, api_dir=api)
    assert [s.name for s in first.pre] == ["seed"] and first.pre[0].cmd == ["uv", "run", "voiceai", "seed", "--reset"] and first.pre[0].cwd == api
    stamp, digest = first.stamp
    assert stamp.parent == api / "data" and stamp.name.startswith("seed-stamp-") and not stamp.exists()  # written only after the step succeeds
    stamp.parent.mkdir()
    stamp.write_text(digest + "\n", encoding="utf-8")
    assert dev.make_plan(args, ["uv"], "npm", environ={}, dotenv={}, api_dir=api).pre == []  # a matching stamp keeps your data
    (api / "voiceai" / "seed" / "loader.py").write_text("SEED = 2\n", encoding="utf-8")
    assert [s.name for s in dev.make_plan(args, ["uv"], "npm", environ={}, dotenv={}, api_dir=api).pre] == ["seed"]  # the seed changed
    stamp.write_text(dev.seed_digest(api, tmp_path) + "\n", encoding="utf-8")
    assert [s.name for s in dev.make_plan(ns(no_reseed=False, reset=True), ["uv"], "npm", environ={}, dotenv={}, api_dir=api).pre] == ["seed"]  # --reset
    assert dev.make_plan(ns(no_reseed=True, reset=True), ["uv"], "npm", environ={}, dotenv={}, api_dir=api).pre == []  # --no-reseed wins
    fake = dev.make_plan(args, ["uv"], "npm", environ={"DATABASE_URL": "sqlite:///x/fake.db"}, dotenv={}, api_dir=api)
    assert fake.pre[0].env["PYTHONUTF8"] == "1" and fake.stamp[0] != stamp  # another database has its own stamp


def _serve(handler_cls):  # noqa: ANN001, ANN202
    import http.server
    import threading as th

    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _platform(sign_in: bool):  # noqa: ANN202
    import http.server

    class Platform(http.server.BaseHTTPRequestHandler):
        seen: list[tuple[str, str, str]] = []

        def _send(self, code: int, body: bytes = b"{}", cookie: str | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: ANN202, N802
            self._send(200)

        def do_POST(self):  # noqa: ANN202, N802
            size = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(size).decode()
            Platform.seen.append((self.path, self.headers.get("Cookie") or "", body))
            if self.path == "/api/auth/login":
                ok = "right-pass" in body
                self._send(200 if ok else 401, cookie="studio_session=abc; Path=/" if ok else None)
            elif self.path == "/api/api-keys":
                if sign_in and "studio_session=abc" not in (self.headers.get("Cookie") or ""):
                    self._send(401, b'{"error": "login_required"}')
                else:
                    self._send(201, b'{"key": "vak_new"}')

        def log_message(self, *a):  # noqa: ANN002, ANN202
            pass

    return Platform


def test_the_chat_key_is_created_through_the_admin_login(tmp_path):
    """Covers: DEV-22"""
    Platform = _platform(sign_in=True)
    srv = _serve(Platform)
    try:
        said: list[str] = []
        assert dev.provision_chat_key(f"http://127.0.0.1:{srv.server_port}", tmp_path, said.append, wait_s=5, admin_pw="right-pass") is True
        assert [p for p, _, _ in Platform.seen] == ["/api/auth/login", "/api/api-keys"]
        assert "studio_session=abc" in Platform.seen[1][1] and "admin@echomind.test" in Platform.seen[0][2]
        assert "VOICEAI_API_KEY=vak_new" in (tmp_path / ".env.local").read_text(encoding="utf-8")
        Platform.seen.clear()
        assert dev.provision_chat_key(f"http://127.0.0.1:{srv.server_port}", tmp_path, said.append, wait_s=5, admin_pw="right-pass") is True
        assert Platform.seen == []  # an existing key is never replaced and nothing is requested
    finally:
        srv.shutdown()


def test_no_login_is_attempted_when_sign_in_is_off(tmp_path):
    """Covers: DEV-22"""
    Platform = _platform(sign_in=False)
    srv = _serve(Platform)
    try:
        assert dev.provision_chat_key(f"http://127.0.0.1:{srv.server_port}", tmp_path, lambda m: None, wait_s=5, admin_pw=None) is True
        assert [p for p, _, _ in Platform.seen] == ["/api/api-keys"]
        wrong = tmp_path / "other"
        wrong.mkdir()
        said: list[str] = []
        assert dev.provision_chat_key(f"http://127.0.0.1:{srv.server_port}", wrong, said.append, wait_s=5, admin_pw="wrong") is False
        assert any("Create a member key in Studio" in m for m in said) and not (wrong / ".env.local").exists()
    finally:
        srv.shutdown()
    assert dev.admin_password({}, {}, {}) is None
    assert dev.admin_password({"STUDIO_ADMIN_PASSWORD": "a"}, {"STUDIO_ADMIN_PASSWORD": "b"}, {}) == "a"
    assert dev.admin_password({}, {}, {"STUDIO_ADMIN_PASSWORD": "d"}) == "d"


def test_banner_shows_passwords_only_when_the_launcher_chose_them():
    """Covers: DEV-23"""
    applied = dev.make_plan(ns(no_login=False, no_chat=False), ["uv"], "npm", environ={}, dotenv={}, chat_dir=REPO / "apps" / "chat")
    lines = dev.banner(ns(no_login=False, no_chat=False), applied)
    text = "\n".join(lines)
    assert "Studio: http://localhost:3000" in text and "Customer chat: http://localhost:3100" in text
    for email, pw in (("admin@echomind.test", "admin-demo-pass"), ("reviewer@echomind.test", "reviewer-demo-pass"), ("specialist@echomind.test", "specialist-demo-pass")):
        assert f"{email} / {pw}" in text
    own = dev.make_plan(ns(no_login=False, no_chat=True), ["uv"], "npm", environ={"STUDIO_ADMIN_PASSWORD": "mine"}, dotenv={})
    quiet = "\n".join(dev.banner(ns(no_chat=True), own))
    assert "mine" not in quiet and "demo-pass" not in quiet and "Customer chat" not in quiet and "Studio:" in quiet


# ---------------------------------------------------------------- supervision
def _printer() -> tuple[io.StringIO, "dev.Printer"]:
    buf = io.StringIO()
    return buf, dev.Printer(buf, color=False, width=3)


def test_every_line_is_prefixed_once(tmp_path):
    """Covers: DEV-03"""
    buf, printer = _printer()
    a = dev.Service("a", [PY, "-u", "-c", "import sys,time; print('out a'); print('err a', file=sys.stderr); time.sleep(0.6)"], tmp_path)
    b = dev.Service("b", [PY, "-u", "-c", "import time; print('out b'); time.sleep(30)"], tmp_path)
    started = time.time()
    outcome = dev.supervise([a, b], printer, install_signals=False)
    text = buf.getvalue()
    for tag, line in (("a", "out a"), ("a", "err a"), ("b", "out b")):
        assert len(re.findall(rf"\[{tag}\]\s+{line}\n", text)) == 1, text
    assert outcome.exited == "a" and outcome.code == 0 and time.time() - started < 15  # b was stopped when a ended


def test_exit_code_and_whole_tree_stopped(tmp_path):
    """Covers: DEV-04"""
    heartbeat = tmp_path / "beat.txt"
    beat_code = "import sys,time\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.05)\n"
    worker_code = "import subprocess,sys,time\nsubprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]])\ntime.sleep(60)\n"
    worker = dev.Service("worker", [PY, "-c", worker_code, str(heartbeat), beat_code], tmp_path)
    failing = dev.Service("fail", [PY, "-c", "import time; time.sleep(1.5); raise SystemExit(3)"], tmp_path)
    _, printer = _printer()
    outcome = dev.supervise([worker, failing], printer, install_signals=False)
    assert outcome.code == 3 and outcome.exited == "fail" and not outcome.interrupted
    size = heartbeat.stat().st_size
    assert size > 0, "the grandchild never started, so this test proved nothing"
    time.sleep(0.7)
    assert heartbeat.stat().st_size == size, "the grandchild is still running"


def test_sigterm_stops_everything_with_code_zero(tmp_path):
    """Covers: DEV-04"""
    _, printer = _printer()
    svc = dev.Service("a", [PY, "-u", "-c", "import time; print('up'); time.sleep(60)"], tmp_path)
    threading.Timer(1.0, lambda: signal.raise_signal(signal.SIGTERM)).start()
    started = time.time()
    outcome = dev.supervise([svc], printer)
    assert outcome.interrupted and outcome.code == 0 and time.time() - started < 15


# ---------------------------------------------------------------- pre-flight
def test_preflight_names_the_fix(tmp_path):
    """Covers: DEV-05"""
    root = _repo(tmp_path, venv=False, node_modules=False)
    errors, _, _ = dev.preflight(ns(), None, None, environ={}, root=root, in_use=lambda p: p == 8000)
    text = "\n".join(errors)
    for needle in ("uv not found", "npm not found", "apps/api/.venv missing", "apps/web/node_modules missing", "port 8000", "--api-port"):
        assert needle in text, (needle, text)
    assert "scripts/setup.py --install" in text
    errors, _, _ = dev.preflight(ns(single_origin=True, skip_build=True), ["uv"], "npm", environ={}, root=_repo(tmp_path / "b", out=False), in_use=lambda p: False)
    assert any("apps/web/out missing" in e for e in errors)


def test_check_flag_exit_codes(tmp_path, monkeypatch, capsys):
    """Covers: DEV-05"""
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    monkeypatch.setattr(dev, "port_in_use", lambda p: False)
    monkeypatch.setattr(dev, "uv_command", lambda: ["uv"])
    monkeypatch.setattr(dev.shutil, "which", lambda name: "npm")
    _repo(tmp_path, venv=False)
    assert dev.main(["--check"]) == 1
    (tmp_path / "apps" / "api" / ".venv").mkdir()
    assert dev.main(["--check"]) == 0
    assert "pre-flight ok" in capsys.readouterr().out


def test_key_warnings_never_leak_values(tmp_path):
    """Covers: DEV-06"""
    root = _repo(tmp_path)
    (root / "apps" / "api" / ".env").write_text("OPENAI_API_KEY=sk_supersecret\nDEEPGRAM_API_KEY=\n# comment\n")
    errors, warnings, status = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert not errors and status == {"OPENROUTER_API_KEY": False, "OPENAI_API_KEY": True, "DEEPGRAM_API_KEY": False}
    assert any("DEEPGRAM_API_KEY" in w and "Type" in w for w in warnings)
    assert not any("agent replies will fail" in w for w in warnings)
    assert "sk_supersecret" not in " ".join(warnings)

    (root / "apps" / "api" / ".env").write_text("OPENROUTER_API_KEY=or-secret\n")  # OpenRouter alone is complete too: no LLM_ROLE_* advice
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert not any("agent replies will fail" in w or "LLM_ROLE_*" in w for w in warnings) and "or-secret" not in " ".join(warnings)
    (root / "apps" / "api" / ".env").write_text("DEEPGRAM_API_KEY=dg\n")  # no LLM key at all
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert any("OPENAI_API_KEY or OPENROUTER_API_KEY" in w for w in warnings)

    # an OpenAI key alone is a complete LLM setup: every role falls back to OpenAI, so no LLM warning and no LLM_ROLE_* advice
    (root / "apps" / "api" / ".env").write_text("OPENAI_API_KEY=sk-supersecret\n")
    _, warnings, status = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert status["OPENAI_API_KEY"] is True
    assert not any("agent replies will fail" in w or "LLM_ROLE_*" in w for w in warnings) and "sk-supersecret" not in " ".join(warnings)
    # OpenRouter plus OpenAI: still no role-line advice, because OpenAI answers for every role
    (root / "apps" / "api" / ".env").write_text("OPENROUTER_API_KEY=or-secret\nOPENAI_API_KEY=sk-supersecret\n")
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert not any("LLM_ROLE_*" in w for w in warnings)

    (root / "apps" / "api" / ".env").write_text("")
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert any("agent replies will fail" in w and "OPENAI_API_KEY" in w for w in warnings)
    _, warnings, _ = dev.preflight(ns(fake=True), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert not any("agent replies will fail" in w for w in warnings)


def test_fake_mode_uses_separate_database():
    """Covers: DEV-06"""
    env = dev.make_plan(ns(fake=True), ["uv"], "npm", environ={}).services[0].env
    assert env["LLM_FAKE"] == "1" and env["EMBEDDINGS_PROVIDER"] == "hash" and env["DATABASE_URL"].endswith("/data/fake.db")
    kept = dev.make_plan(ns(fake=True), ["uv"], "npm", environ={"DATABASE_URL": "sqlite+aiosqlite:///x.db"}).services[0].env
    assert "DATABASE_URL" not in kept  # an explicit DATABASE_URL is left alone


# ---------------------------------------------------------------- dental demo mock (CP-0038)
def test_plan_starts_the_dental_mock():
    """Covers: DEV-12"""
    for args in (ns(), ns(single_origin=True)):
        mock = next(s for s in dev.make_plan(args, ["uv"], "npm", environ={}).services if s.name == "mock")
        assert mock.cmd[0] == sys.executable and mock.cmd[1].endswith(str(Path("scripts", "demo", "dental_mock.py")))
        assert mock.cmd[2:] == ["--port", "8766"]
    plan = dev.make_plan(ns(mock_port=9001), ["uv"], "npm", environ={})
    assert plan.services[-1].cmd[-1] == "9001" and plan.ready["mock"] == "http://127.0.0.1:9001/dental/health"
    assert all(s.name != "mock" for s in dev.make_plan(ns(no_mock=True), ["uv"], "npm", environ={}).services)


def test_busy_mock_port_is_never_an_error(tmp_path):
    """Covers: DEV-13"""
    root = _repo(tmp_path)
    busy = lambda p: p == 8766  # noqa: E731
    errors, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=busy, health=lambda p: True)
    assert errors == [] and not any("8766" in w for w in warnings)
    assert dev.mock_decision(ns(), busy, lambda p: True) == (False, None)  # reused: the plan gets no mock
    errors, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=busy, health=lambda p: False)
    assert errors == [] and any("8766" in w and "dental" in w for w in warnings)
    start, _ = dev.mock_decision(ns(), busy, lambda p: False)
    assert start is False
    assert all(s.name != "mock" for s in dev.make_plan(ns(), ["uv"], "npm", environ={}, start_mock=start).services)
    assert dev.mock_decision(ns(), lambda p: False, lambda p: False) == (True, None)


def test_demo_kits_reuse_a_running_mock(monkeypatch):
    """Covers: DEV-14"""
    sys.path.insert(0, str(REPO / "scripts"))
    sys.path.insert(0, str(REPO / "scripts" / "demo"))
    spec = importlib.util.spec_from_file_location("demo_kits_under_test", REPO / "scripts" / "demo_kits.py")
    kits = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = kits
    spec.loader.exec_module(kits)  # type: ignore[union-attr]
    server, port, _ = kits.dental_mock.serve(0)
    try:
        assert kits.mock_running(port)
        # every dental tool, the claim documents too, is served by this mock (the platform's claim-requirements mock is retired)
        assert all(t["url"].startswith("{mock}/dental/") for t in kits.KITS["dental"].tools)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/dental/claim-documents?claim_type=dental", timeout=5) as resp:
            assert json.loads(resp.read())["documents"]
        seen: list[str] = []

        class Runner:  # records the mock base the kit would give its tools
            def __init__(self, args, kit, mock_base):  # noqa: ANN001
                seen.append(mock_base)
                self.kit, self.agent_id, self.results = kit, None, []

            def build(self) -> bool:
                return False

        def no_second_mock(_port: int):  # noqa: ANN202
            raise AssertionError("a running mock must be reused")

        monkeypatch.setattr(kits, "Runner", Runner)
        monkeypatch.setattr(kits.dental_mock, "serve", no_second_mock)
        kits.run_kits(argparse.Namespace(mock_port=port, check=True), ["dental"])
        assert seen == [f"http://127.0.0.1:{port}"]
    finally:
        server.shutdown()

