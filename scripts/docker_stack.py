#!/usr/bin/env python3
"""Run the whole stack (web app, API, dental demo mock and the customer chat app) in local Docker containers.

Spec: /build/docker-stack.md

    python scripts/docker_stack.py start              # build voiceai:local and run it on http://localhost:8080
    python scripts/docker_stack.py start --skip-build # reuse the last image
    python scripts/docker_stack.py start --port 9090  # another host port
    python scripts/docker_stack.py start --no-chat    # without the customer chat app (also --no-login, --reset, --no-reseed, --chat-port)
    python scripts/docker_stack.py status | logs [-f] [-n 100] | stop

Use it where the voice pipeline cannot load on the machine itself (for example Windows Application Control blocking its
native libraries): a Linux container is not subject to that policy. The container uses the local database
(apps/api/data) and the keys in apps/api/.env, so stop `dev.py` first. One command does everything (CP-0054): the chat app
in its own container, demo logins when no Studio password is set, the demo data re-seeded when the seed changed, and the chat
key created through the admin login. Stdlib only; needs Docker with its engine running.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402 - the login defaults, seed stamp and chat key of CP-0053, shared with the dev launcher

API_DIR = ROOT / "apps" / "api"
CHAT_DIR = ROOT / "apps" / "chat"
IMAGE = "voiceai:local"
CONTAINER = "voiceai-local"
CHAT_IMAGE = "voiceai-chat:local"
CHAT_CONTAINER = "voiceai-chat"
CHAT_CONTAINER_PORT = 3100
STAMP_KEY = "docker"  # one database (apps/api/data/voiceai.db) behind this launcher
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
    data = f"{root / 'apps' / 'api' / 'data'}:/app/apps/api/data"
    run = [
        "docker", "run", "-d", "--name", CONTAINER,
        "-p", f"{args.port}:{CONTAINER_PORT}",
        "-v", data,
        "--env-file", "{env_file}",
        IMAGE, *container_command(not args.no_mock),
    ]
    env = read_dotenv(root / "apps" / "api" / ".env")
    logins = dev.login_defaults(args, {}, env)  # DEV-26: demo passwords only when none of the three is set
    env = {**env, **logins}
    chat = not getattr(args, "no_chat", False)
    chat_port = getattr(args, "chat_port", dev.CHAT_PORT)
    chat_build = None if (args.skip_build or not chat) else [
        "docker", "build", "-f", str(root / "apps" / "chat" / "Dockerfile"), "-t", CHAT_IMAGE, str(root / "apps" / "chat")]
    chat_run = [
        "docker", "run", "-d", "--name", CHAT_CONTAINER, "-p", f"{chat_port}:{CHAT_CONTAINER_PORT}",
        "--add-host", "host.docker.internal:host-gateway", "--env-file", "{env_file}", CHAT_IMAGE] if chat else None
    seed = None
    if not getattr(args, "no_reseed", False):  # DEV-25: one-off container, before the API container opens the database
        digest = dev.seed_digest(root / "apps" / "api", root)
        stamp = dev.seed_stamp_path(STAMP_KEY, root / "apps" / "api")
        if dev.seed_needed(args, stamp, digest):
            seed = {"run": ["docker", "run", "--rm", "-v", data, "--env-file", "{env_file}", IMAGE,
                            "sh", "-c", "uv run --no-sync voiceai seed --reset"], "stamp": (stamp, digest)}
    return {"build": build, "run": run, "env": env, "logins": logins, "chat_build": chat_build, "chat_run": chat_run,
            "seed": seed, "chat_port": chat_port}


def chat_env(args: argparse.Namespace, key: str, chat_dir: Path = CHAT_DIR) -> dict[str, str]:
    """DEV-27: the chat container's settings (the key comes from apps/chat/.env.local)."""
    local = dev.read_dotenv(chat_dir / ".env.local")
    env = {"VOICEAI_API_URL": f"http://host.docker.internal:{args.port}", "VOICEAI_TENANT_ID": local.get("VOICEAI_TENANT_ID", "northgate-health"),
           "VOICEAI_API_KEY": key}
    if local.get("CHAT_BRAND_NAME"):
        env["CHAT_BRAND_NAME"] = local["CHAT_BRAND_NAME"]
    return env


def ensure_chat_key(args: argparse.Namespace, chat_dir: Path, logins: dict[str, str], api_env: dict[str, str],
                    say=print, wait_s: float = 20.0) -> str | None:  # noqa: ANN001
    """DEV-27: the chat key from apps/chat/.env.local, created through the admin login when missing."""
    if dev.chat_key_needed(chat_dir, environ={}):
        pw = dev.admin_password(logins, {}, api_env)
        if not dev.provision_chat_key(f"http://localhost:{args.port}", chat_dir, lambda m: say(f"[docker] {m}"), wait_s=wait_s, admin_pw=pw):
            return None
    return dev.read_dotenv(chat_dir / ".env.local").get("VOICEAI_API_KEY") or None


def write_env_file(values: dict[str, str]) -> str:
    fd, path = tempfile.mkstemp(prefix="voiceai-env-", suffix=".list")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for k, v in values.items():
            if "\n" not in v:
                f.write(f"{k}={v}\n")
    return path


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


def chat_running_port() -> int | None:
    try:
        out = docker("ps", "--filter", f"name=^{CHAT_CONTAINER}$", "--format", "{{.Ports}}").stdout.strip()
    except OSError:
        return None
    for part in out.split(","):
        if f"->{CHAT_CONTAINER_PORT}/tcp" in part and ":" in part:
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
              local_api: bool | None = None, in_use: bool | None = None, chat_busy: bool | None = None) -> list[str]:
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
    chat_port = getattr(args, "chat_port", dev.CHAT_PORT)
    if not getattr(args, "no_chat", False):
        busy = chat_busy if chat_busy is not None else (chat_running_port() != chat_port and port_in_use(chat_port))
        if busy:
            errors.append(f"port {chat_port} is already in use. Free it or pass --chat-port <free port> (or --no-chat)")
    return errors


def start(args: argparse.Namespace) -> int:
    errors = preflight(args)
    for e in errors:
        print(f"[docker] error: {e}")
    if errors:
        return 1
    p = plan(args)
    for label, key in (("", "build"), ("chat ", "chat_build")):
        if p[key]:
            print(f"[docker] building the {label}image (the first build takes a few minutes)", flush=True)
            if subprocess.run(p[key]).returncode != 0:  # type: ignore[arg-type]
                print(f"[docker] {label}build failed; see the output above")
                return 1
    docker("rm", "-f", CONTAINER, CHAT_CONTAINER)  # also frees the database before a seed
    env: dict[str, str] = p["env"]  # type: ignore[assignment]
    logins: dict[str, str] = p["logins"]  # type: ignore[assignment]
    env_path = write_env_file(env)
    try:
        seed = p["seed"]
        if seed:  # DEV-25: the demo data follows the seed; the stamp is written only after it succeeded
            print("[docker] re-seeding the demo data (the seed changed, or --reset); one moment", flush=True)
            result = subprocess.run([env_path if part == "{env_file}" else part for part in seed["run"]], capture_output=True, text=True)  # type: ignore[index]
            if result.returncode != 0:
                print(f"[docker] the seed failed: {(result.stderr or result.stdout).strip()[-800:]}")
                return 1
            stamp, digest = seed["stamp"]  # type: ignore[index]
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(digest + "\n", encoding="utf-8")
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
    ready = False
    while time.time() < deadline:
        if answers(f"{url}/healthz", 3):
            ready = True
            break
        if not running_port():
            break
        time.sleep(2)
    if not ready:
        print("[docker] the API did not become ready; last log lines:")
        print(docker("logs", "--tail", "30", CONTAINER).stdout + docker("logs", "--tail", "30", CONTAINER).stderr)
        return 1
    lines = [f"Studio: {url}"]
    if p["chat_run"]:
        key = ensure_chat_key(args, CHAT_DIR, logins, env)
        if not key:
            print("[docker] the chat app was not started: no chat key (see above). Studio is ready.")
        else:
            chat_path = write_env_file(chat_env(args, key))
            try:
                result = subprocess.run([chat_path if part == "{env_file}" else part for part in p["chat_run"]], capture_output=True, text=True)  # type: ignore[union-attr]
            finally:
                os.unlink(chat_path)
            chat_url = f"http://localhost:{p['chat_port']}"
            if result.returncode != 0:
                print(f"[docker] could not start the chat container: {result.stderr.strip()}")
            else:
                for _ in range(30):
                    if answers(chat_url + "/", 3):
                        break
                    time.sleep(1)
                lines.append(f"Customer chat: {chat_url}")
    if logins:
        lines.append("Demo sign-in (local only; set your own STUDIO_*_PASSWORD in apps/api/.env to change):")
        lines += [f"  {role}: {email} / {logins[name]}" for email, name, _, role in dev.DEMO_LOGINS]
    print("[docker] READY - open " + lines[0].split(": ", 1)[1])
    for line in lines:
        print(f"[docker] {line}")
    return 0


def status(_: argparse.Namespace) -> int:
    port = running_port()
    if port is None:
        print(f"[docker] {CONTAINER} is not running (python scripts/docker_stack.py start)")
        return 1
    ok = answers(f"http://localhost:{port}/healthz", 3)
    print(f"[docker] {CONTAINER} running on http://localhost:{port}  healthz: {'ok' if ok else 'not answering'}")
    chat = chat_running_port()
    print(f"[docker] {CHAT_CONTAINER} " + (f"running on http://localhost:{chat}" if chat else "is not running"))
    return 0 if ok else 1


def logs(args: argparse.Namespace) -> int:
    name = CHAT_CONTAINER if getattr(args, "service", "api") == "chat" else CONTAINER
    cmd = ["docker", "logs", "--tail", str(args.n), *(["-f"] if args.follow else []), name]
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


def stop(_: argparse.Namespace) -> int:
    removed = [name for name in (CONTAINER, CHAT_CONTAINER) if docker("rm", "-f", name).returncode == 0]
    print(f"[docker] removed: {', '.join(removed)}" if removed else "[docker] nothing was running")
    return 0 if removed else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="build and run the container")
    s.add_argument("--port", type=int, default=8080, help="host port for the web app and API (default 8080)")
    s.add_argument("--skip-build", action="store_true", help="reuse the last voiceai:local image")
    s.add_argument("--no-mock", action="store_true", help="do not start the dental demo mock in the container")
    s.add_argument("--force", action="store_true", help="start even while a local API runs on :8000")
    s.add_argument("--no-chat", action="store_true", help="do not run the customer chat app")
    s.add_argument("--chat-port", type=int, default=dev.CHAT_PORT, help="host port of the chat app (default 3100)")
    s.add_argument("--no-login", action="store_true", help="do not give the API demo Studio passwords")
    s.add_argument("--reset", action="store_true", help="re-seed the demo data before starting")
    s.add_argument("--no-reseed", action="store_true", help="never re-seed, even when the seed changed")
    s.add_argument("--timeout", type=int, default=240, help="seconds to wait for /healthz")
    sub.add_parser("status", help="is it running, and healthy?")
    lg = sub.add_parser("logs", help="container logs")
    lg.add_argument("-n", type=int, default=100)
    lg.add_argument("-f", "--follow", action="store_true")
    lg.add_argument("--service", choices=["api", "chat"], default="api", help="which container (default api)")
    sub.add_parser("stop", help="remove the container (the image and the database stay)")
    args = ap.parse_args(argv)
    return {"start": start, "status": status, "logs": logs, "stop": stop}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
