#!/usr/bin/env python3
"""Bootstrap a clone on any machine (Windows, macOS, Linux).

Spec: /process/sdd-workflow.md (Onboarding, SDD-09), /build/runbook-local.md

    python scripts/setup.py             # hooks + apps/api/.env + prerequisite report + spec check
    python scripts/setup.py --install   # also: uv sync (backend) and npm ci (web)

Stdlib only. On Windows without a `python` command use `py -3 scripts/setup.py`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path | None = None) -> bool:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd or ROOT).returncode == 0


def configure_hooks(root: Path = ROOT) -> bool:
    """Point git at the repo's hooks (SDD-09). Needs a git checkout."""
    if not (root / ".git").exists():
        print("  ! not a git checkout; skipping hooks")
        return False
    return subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root).returncode == 0


def ensure_env(root: Path = ROOT) -> str:
    """Create apps/api/.env from the example; never overwrite an existing one (SDD-09)."""
    env, example = root / "apps" / "api" / ".env", root / "apps" / "api" / ".env.example"
    if env.exists():
        return "exists"
    if not example.exists():
        return "missing-example"
    shutil.copyfile(example, env)
    return "created"


def uv_command() -> list[str] | None:
    if shutil.which("uv"):
        return ["uv"]
    try:
        if subprocess.run([sys.executable, "-m", "uv", "--version"], capture_output=True).returncode == 0:
            return [sys.executable, "-m", "uv"]
    except OSError:
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", action="store_true", help="also install backend (uv sync) and web (npm ci) dependencies")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # keep our output ordered with child-process output

    print("1. Git hooks")
    print("  ok: core.hooksPath = .githooks" if configure_hooks() else "  ! hooks not configured")

    print("2. Environment file")
    state = ensure_env()
    print({"created": "  created apps/api/.env - add GROQ_API_KEY and DEEPGRAM_API_KEY",
           "exists": "  apps/api/.env already exists (left untouched)",
           "missing-example": "  ! apps/api/.env.example not found"}[state])

    print("3. Prerequisites")
    ok_py = sys.version_info >= (3, 9)
    uv = uv_command()
    node, npm = shutil.which("node"), shutil.which("npm")
    print(f"  python {sys.version.split()[0]}: {'ok' if ok_py else 'need 3.9+ for the spec tooling (3.12 for the backend)'}")
    print(f"  uv: {'ok' if uv else 'missing -> https://docs.astral.sh/uv/ (or: python -m pip install --user uv)'}")
    print(f"  node/npm: {'ok' if node and npm else 'missing -> install Node.js LTS from https://nodejs.org'}")
    print(f"  git: {'ok' if shutil.which('git') else 'missing'}")

    if args.install:
        print("4. Dependencies")
        if uv:
            run([*uv, "sync"], ROOT / "apps" / "api")
        if npm:
            run([npm, "ci", "--no-audit", "--no-fund"], ROOT / "apps" / "web")
        if not uv and not npm:
            print("  nothing to install: uv and npm are both missing")

    print("5. Spec check")
    ok = run([sys.executable, str(ROOT / "scripts" / "spec_check.py")])
    print("\nNext: edit apps/api/.env, then see README.md > Run it, or start spec-first with /spec-change.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
