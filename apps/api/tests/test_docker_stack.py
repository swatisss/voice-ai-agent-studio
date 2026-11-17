"""scripts/docker_stack.py: the container plan and the refusal while a local API runs (no Docker needed).

Covers: DEV-15, DEV-16, DEV-24, DEV-25, DEV-26, DEV-27
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("docker_stack", REPO / "scripts" / "docker_stack.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ds = _load()


def ns(**kw) -> argparse.Namespace:  # noqa: ANN003
    return argparse.Namespace(**{"port": 8080, "skip_build": False, "no_mock": False, "force": False, "timeout": 5,
                                 "no_chat": True, "chat_port": 3100, "no_login": True, "reset": False, "no_reseed": True, **kw})  # older tests opt out of the CP-0054 defaults


def _root(tmp: Path) -> Path:
    (tmp / "apps" / "api" / "data").mkdir(parents=True)
    (tmp / "apps" / "api" / ".env").write_text(
        'OPENAI_API_KEY="sk-test-not-real"\nDEEPGRAM_API_KEY=dg-test\n# comment\nDATABASE_URL=sqlite:///C:/x.db\n', encoding="utf-8")
    return tmp


def test_plan_runs_app_and_mock_with_local_data_and_env(tmp_path, capsys):
    """Covers: DEV-15"""
    root = _root(tmp_path)
    p = ds.plan(ns(), root)
    assert p["build"] == ["docker", "build", "-f", str(root / "infra" / "Dockerfile"), "-t", "voiceai:local", str(root)]
    run = p["run"]
    assert run[:5] == ["docker", "run", "-d", "--name", "voiceai-local"]
    assert run[run.index("-p") + 1] == "8080:8080"
    assert run[run.index("-v") + 1] == f"{root / 'apps' / 'api' / 'data'}:/app/apps/api/data"
    assert run[run.index("--env-file") + 1] == "{env_file}"
    cmd = run[-1]
    assert cmd.index("dental_mock.py --port 8766 &") < cmd.index("voiceai serve --host 0.0.0.0 --port 8080")
    assert p["env"] == {"OPENAI_API_KEY": "sk-test-not-real", "DEEPGRAM_API_KEY": "dg-test"}  # quotes stripped, host DB path dropped
    assert "sk-test-not-real" not in capsys.readouterr().out
    assert ds.plan(ns(skip_build=True), root)["build"] is None
    run9 = ds.plan(ns(port=9090), root)["run"]
    assert run9[run9.index("-p") + 1] == "9090:8080"
    assert "dental_mock" not in ds.plan(ns(no_mock=True), root)["run"][-1]


def test_refuses_while_a_local_api_runs(tmp_path):
    """Covers: DEV-16"""
    root = _root(tmp_path)
    errors = ds.preflight(ns(), root=root, engine_ok=True, ours=None, local_api=True, in_use=False)
    assert len(errors) == 1 and ":8000" in errors[0] and "voiceai.db" in errors[0]
    assert ds.preflight(ns(force=True), root=root, engine_ok=True, ours=None, local_api=True, in_use=False) == []
    assert ds.preflight(ns(), root=root, engine_ok=False) and "Docker" in ds.preflight(ns(), root=root, engine_ok=False)[0]
    assert ds.preflight(ns(), root=root, engine_ok=True, ours=None, local_api=False, in_use=False) == []
    busy = ds.preflight(ns(no_chat=False), root=root, engine_ok=True, ours=None, local_api=False, in_use=False, chat_busy=True)
    assert len(busy) == 1 and "3100" in busy[0] and "--chat-port" in busy[0]


def _seed_root(tmp: Path) -> Path:
    root = _root(tmp)
    (root / "apps" / "api" / "voiceai" / "seed").mkdir(parents=True)
    (root / "apps" / "api" / "voiceai" / "seed" / "loader.py").write_text("SEED = 1\n", encoding="utf-8")
    (root / "specs" / "demo-data").mkdir(parents=True)
    (root / "specs" / "demo-data" / "members.md").write_text("Sarah\n", encoding="utf-8")
    return root


def test_plan_builds_and_runs_the_chat_container(tmp_path):
    """Covers: DEV-24"""
    root = _root(tmp_path)
    p = ds.plan(ns(no_chat=False), root)
    assert p["chat_build"] == ["docker", "build", "-f", str(root / "apps" / "chat" / "Dockerfile"), "-t", "voiceai-chat:local", str(root / "apps" / "chat")]
    run = p["chat_run"]
    assert run[:5] == ["docker", "run", "-d", "--name", "voiceai-chat"] and run[run.index("-p") + 1] == "3100:3100"
    assert run[run.index("--add-host") + 1] == "host.docker.internal:host-gateway" and run[run.index("--env-file") + 1] == "{env_file}"
    assert ds.plan(ns(no_chat=False, skip_build=True), root)["chat_build"] is None
    assert ds.plan(ns(no_chat=False, chat_port=3200), root)["chat_run"][run.index("-p") + 1] == "3200:3100"
    off = ds.plan(ns(no_chat=True), root)
    assert off["chat_build"] is None and off["chat_run"] is None


def test_seed_runs_once_in_a_one_off_container_before_the_api(tmp_path):
    """Covers: DEV-25"""
    root = _seed_root(tmp_path)
    p = ds.plan(ns(no_reseed=False), root)
    seed = p["seed"]
    assert seed["run"][:3] == ["docker", "run", "--rm"] and seed["run"][-1] == "uv run --no-sync voiceai seed --reset"
    assert f"{root / 'apps' / 'api' / 'data'}:/app/apps/api/data" in seed["run"] and "{env_file}" in seed["run"] and "voiceai:local" in seed["run"]
    stamp, digest = seed["stamp"]
    assert not stamp.exists()  # written by start() only after the seed container succeeds
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(digest + "\n", encoding="utf-8")
    assert ds.plan(ns(no_reseed=False), root)["seed"] is None  # a matching stamp keeps the data
    assert ds.plan(ns(no_reseed=False, reset=True), root)["seed"] is not None
    assert ds.plan(ns(no_reseed=True, reset=True), root)["seed"] is None
    (root / "apps" / "api" / "voiceai" / "seed" / "loader.py").write_text("SEED = 2\n", encoding="utf-8")
    assert ds.plan(ns(no_reseed=False), root)["seed"] is not None  # the seed changed


def test_demo_passwords_reach_the_api_container_only_when_none_is_set(tmp_path):
    """Covers: DEV-26"""
    root = _root(tmp_path)
    names = ["STUDIO_ADMIN_PASSWORD", "STUDIO_REVIEWER_PASSWORD", "STUDIO_SPECIALIST_PASSWORD"]
    given = ds.plan(ns(no_login=False), root)
    assert [given["env"][n] for n in names] == ["admin-demo-pass", "reviewer-demo-pass", "specialist-demo-pass"] and given["logins"]
    env_file = root / "apps" / "api" / ".env"
    env_file.write_text(env_file.read_text(encoding="utf-8") + "STUDIO_ADMIN_PASSWORD=\nSTUDIO_REVIEWER_PASSWORD=mine\n", encoding="utf-8")
    own = ds.plan(ns(no_login=False), root)
    assert own["env"]["STUDIO_REVIEWER_PASSWORD"] == "mine" and own["logins"] == {} and "STUDIO_SPECIALIST_PASSWORD" not in own["env"]
    assert ds.plan(ns(no_login=True), _root(tmp_path / "b"))["logins"] == {}


def test_chat_key_comes_from_the_admin_login_and_reaches_the_chat_container(tmp_path):
    """Covers: DEV-27"""
    from tests.test_dev_launcher import _platform, _serve  # noqa: PLC0415

    Platform = _platform(sign_in=True)
    srv = _serve(Platform)
    try:
        chat_dir = tmp_path / "chat"
        chat_dir.mkdir()
        said: list[str] = []
        args = ns(port=srv.server_port, no_chat=False)
        logins = {"STUDIO_ADMIN_PASSWORD": "right-pass"}
        key = ds.ensure_chat_key(args, chat_dir, logins, {}, say=said.append, wait_s=5)
        assert key == "vak_new" and [p for p, _, _ in Platform.seen] == ["/api/auth/login", "/api/api-keys"]
        Platform.seen.clear()
        assert ds.ensure_chat_key(args, chat_dir, logins, {}, say=said.append, wait_s=5) == "vak_new" and Platform.seen == []  # nothing created twice
        env = ds.chat_env(args, key, chat_dir)
        assert env["VOICEAI_API_URL"] == f"http://host.docker.internal:{srv.server_port}" and env["VOICEAI_API_KEY"] == "vak_new"
        assert env["VOICEAI_TENANT_ID"] == "northgate-health"
        wrong = tmp_path / "wrong"
        wrong.mkdir()
        assert ds.ensure_chat_key(args, wrong, {"STUDIO_ADMIN_PASSWORD": "nope"}, {}, say=said.append, wait_s=5) is None
    finally:
        srv.shutdown()
    assert ds.CHAT_CONTAINER == "voiceai-chat" and ds.CONTAINER == "voiceai-local"  # stop removes both names
