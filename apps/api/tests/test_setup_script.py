"""Onboarding script. Covers: SDD-09"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("setup_script", REPO / "scripts" / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_hooks_and_env_are_configured_without_clobbering(tmp_path):
    """Covers: SDD-09"""
    mod = _load()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / ".env.example").write_text("GROQ_API_KEY=\n")

    assert mod.configure_hooks(tmp_path) is True
    hooks = subprocess.run(["git", "config", "core.hooksPath"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert hooks == ".githooks"

    assert mod.ensure_env(tmp_path) == "created"
    env = tmp_path / "apps" / "api" / ".env"
    assert env.read_text() == "GROQ_API_KEY=\n"
    env.write_text("GROQ_API_KEY=secret\n")  # a developer's real keys must survive a re-run
    assert mod.ensure_env(tmp_path) == "exists"
    assert env.read_text() == "GROQ_API_KEY=secret\n"


def test_hooks_skipped_outside_git(tmp_path):
    """Covers: SDD-09"""
    assert _load().configure_hooks(tmp_path) is False
