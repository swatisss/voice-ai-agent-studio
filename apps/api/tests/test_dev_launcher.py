"""scripts/dev.py: plan building, pre-flight, prefixed output and process-tree shutdown.

Covers: DEV-01, DEV-02, DEV-03, DEV-04, DEV-05, DEV-06
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import re
import signal
import sys
import threading
import time
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
    base = dict(single_origin=False, skip_build=False, api_port=8000, web_port=3000, no_reload=False, fake=False, install=False, check=False)
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
    api, web = plan.services
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
    assert [s.name for s in plan.services] == ["api"] and "--reload" not in plan.services[0].cmd
    assert plan.open_url == "http://localhost:8000"
    assert dev.make_plan(ns(single_origin=True, skip_build=True), ["uv"], "npm", environ={}).pre == []


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
    (root / "apps" / "api" / ".env").write_text("GROQ_API_KEY=gsk_supersecret\nDEEPGRAM_API_KEY=\n# comment\n")
    errors, warnings, status = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert not errors and status == {"GROQ_API_KEY": True, "OPENROUTER_API_KEY": False, "OPENAI_API_KEY": False, "DEEPGRAM_API_KEY": False}
    assert any("DEEPGRAM_API_KEY" in w and "Type" in w for w in warnings)
    assert not any("agent replies will fail" in w for w in warnings)
    assert "gsk_supersecret" not in " ".join(warnings)

    (root / "apps" / "api" / ".env").write_text("OPENROUTER_API_KEY=or-secret\n")
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={}, root=root, in_use=lambda p: False)
    assert any("LLM_ROLE_*" in w for w in warnings) and "or-secret" not in " ".join(warnings)
    _, warnings, _ = dev.preflight(ns(), ["uv"], "npm", environ={"LLM_ROLE_REALTIME": "openrouter:openai/gpt-oss-120b"}, root=root, in_use=lambda p: False)
    assert not any("LLM_ROLE_*" in w for w in warnings)

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
