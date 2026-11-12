#!/usr/bin/env python3
"""Run the whole stack (web app, API and the dental demo mock) in one local Docker container.

Spec: /build/docker-stack.md

    python scripts/docker_stack.py start              # build voiceai:local and run it on http://localhost:8080
    python scripts/docker_stack.py start --skip-build # reuse the last image
    python scripts/docker_stack.py start --port 9090  # another host port
    python scripts/docker_stack.py status | logs [-f] [-n 100] | stop

Use it where the voice pipeline cannot load on the machine itself (for example Windows Application Control blocking its
native libraries): a Linux container is not subject to that policy. The container uses the local database
(apps/api/data) and the keys in apps/api/.env, so stop `dev.py` first. Stdlib only; needs Docker with its engine running.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "apps" / "api"
IMAGE = "voiceai:local"
CONTAINER = "voiceai-local"
CONTAINER_PORT = 8080
MOCK_PORT = 8766
LOCAL_API = "http://127.0.0.1:8000/healthz"
SKIP_ENV = {"DATABASE_URL", "PORT", "FASTEMBED_CACHE", "SPECS_DIR"}  # host paths and ports mean nothing in the container


def read_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines with surrounding quotes stripped (docker --env-file would keep them)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in SKIP_ENV:
            values[key] = value
    return values


def container_command(mock: bool) -> list[str]:
    serve = f"exec uv run --no-sync voiceai serve --host 0.0.0.0 --port {CONTAINER_PORT}"
    if not mock:
        return ["sh", "-c", serve]
    return ["sh", "-c", f"python3 /app/scripts/demo/dental_mock.py --port {MOCK_PORT} & {serve}"]


def plan(args: argparse.Namespace, root: Path = ROOT) -> dict[str, object]:
    """What `start` runs (DEV-15). `env_file` is a placeholder for the temporary file written at start."""
    build = None if args.skip_build else ["docker", "build", "-f", str(root / "infra" / "Dockerfile"), "-t", IMAGE, str(root)]
    run = [
        "docker", "run", "-d", "--name", CONTAINER,
        "-p", f"{args.port}:{CONTAINER_PORT}",
        "-v", f"{root / 'apps' / 'api' / 'data'}:/app/apps/api/data",
        "--env-file", "{env_file}",
        IMAGE, *container_command(not args.no_mock),
    ]
    return {"build": build, "run": run, "env": read_dotenv(root / "apps" / "api" / ".env")}


def docker(*cmd: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *cmd], capture_output=capture, text=True, encoding="utf-8", errors="replace")


def running_port() -> int | None:
    """The host port our container publishes, or None when it is not running."""
    try:
        out = docker("ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Ports}}").stdout.strip()
    except OSError:
        return None
    if not out:
        return None
    for part in out.split(","):  # 0.0.0.0:8080->8080/tcp
        if f"->{CONTAINER_PORT}/tcp" in part and ":" in part:
            try:
                return int(part.split("->")[0].rsplit(":", 1)[1])
            except ValueError:
                pass
    return None


def answers(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def preflight(args: argparse.Namespace, *, root: Path = ROOT, engine_ok: bool | None = None, ours: int | None = -1,
              local_api: bool | None = None, in_use: bool | None = None) -> list[str]:
    """Errors that stop `start` (DEV-16). Arguments after `root` replace the live checks in tests."""
    errors: list[str] = []
    if engine_ok is None:
        try:
            engine_ok = docker("version", "--format", "{{.Server.Version}}").returncode == 0
        except OSError:
            engine_ok = False
    if not engine_ok:
        errors.append("Docker is not available or its engine is not running. Start Docker Desktop and retry.")
        return errors
    if not (root / "apps" / "api" / ".env").exists():
        errors.append("apps/api/.env not found: run python scripts/setup.py first and add the keys")
    ours = running_port() if ours == -1 else ours
    if local_api is None:
        local_api = ours != 8000 and answers(LOCAL_API)
    if local_api and not args.force:
        errors.append("a local API is running on :8000 (dev.py?). Stop it first: both would write apps/api/data/voiceai.db "
                      "through the Docker mount and could corrupt it. Or pass --force.")
    if in_use is None:
        in_use = ours != args.port and port_in_use(args.port)
    if in_use:
        errors.append(f"port {args.port} is already in use. Free it or pass --port <free port>")
    return errors


def start(args: argparse.Namespace) -> int:
    errors = preflight(args)
    for e in errors:
        print(f"[docker] error: {e}")
    if errors:
        return 1
    p = plan(args)
    if p["build"]:
        print(f"[docker] building {IMAGE} (the first build takes a few minutes)", flush=True)
        if subprocess.run(p["build"]).returncode != 0:  # type: ignore[arg-type]
            print("[docker] build failed; see the output above")
            return 1
    docker("rm", "-f", CONTAINER)
    env: dict[str, str] = p["env"]  # type: ignore[assignment]
    fd, env_path = tempfile.mkstemp(prefix="voiceai-env-", suffix=".list")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for k, v in env.items():
                if "\n" not in v:
                    f.write(f"{k}={v}\n")
        run = [env_path if part == "{env_file}" else part for part in p["run"]]  # type: ignore[union-attr]
        result = subprocess.run(run, capture_output=True, text=True)
    finally:
        os.unlink(env_path)  # the keys never stay on disk outside apps/api/.env
    if result.returncode != 0:
        print(f"[docker] could not start the container: {result.stderr.strip()}")
        return 1
    print(f"[docker] container {CONTAINER} started with {len(env)} settings from apps/api/.env"
          + ("" if args.no_mock else f" and the dental demo mock on :{MOCK_PORT} inside it"), flush=True)
    url = f"http://localhost:{args.port}"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if answers(f"{url}/healthz", 3):
            print(f"[docker] READY - open {url}")
            return 0
        if not running_port():
            break
        time.sleep(2)
    print("[docker] the API did not become ready; last log lines:")
    print(docker("logs", "--tail", "30", CONTAINER).stdout + docker("logs", "--tail", "30", CONTAINER).stderr)
    return 1


def status(_: argparse.Namespace) -> int:
    port = running_port()
    if port is None:
        print(f"[docker] {CONTAINER} is not running (python scripts/docker_stack.py start)")
        return 1
    ok = answers(f"http://localhost:{port}/healthz", 3)
    print(f"[docker] {CONTAINER} running on http://localhost:{port}  healthz: {'ok' if ok else 'not answering'}")
    return 0 if ok else 1


def logs(args: argparse.Namespace) -> int:
    cmd = ["docker", "logs", "--tail", str(args.n), *(["-f"] if args.follow else []), CONTAINER]
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


def stop(_: argparse.Namespace) -> int:
    r = docker("rm", "-f", CONTAINER)
    print(f"[docker] {CONTAINER} removed" if r.returncode == 0 else f"[docker] {r.stderr.strip()}")
    return 0 if r.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="build and run the container")
    s.add_argument("--port", type=int, default=8080, help="host port for the web app and API (default 8080)")
    s.add_argument("--skip-build", action="store_true", help="reuse the last voiceai:local image")
    s.add_argument("--no-mock", action="store_true", help="do not start the dental demo mock in the container")
    s.add_argument("--force", action="store_true", help="start even while a local API runs on :8000")
    s.add_argument("--timeout", type=int, default=240, help="seconds to wait for /healthz")
    sub.add_parser("status", help="is it running, and healthy?")
    lg = sub.add_parser("logs", help="container logs")
    lg.add_argument("-n", type=int, default=100)
    lg.add_argument("-f", "--follow", action="store_true")
    sub.add_parser("stop", help="remove the container (the image and the database stay)")
    args = ap.parse_args(argv)
    return {"start": start, "status": status, "logs": logs, "stop": stop}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
