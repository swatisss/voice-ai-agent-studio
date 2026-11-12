"""scripts/docker_stack.py: the container plan and the refusal while a local API runs (no Docker needed).

Covers: DEV-15, DEV-16
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
    return argparse.Namespace(**{"port": 8080, "skip_build": False, "no_mock": False, "force": False, "timeout": 5, **kw})


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
