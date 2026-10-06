#!/usr/bin/env python3
"""Start the whole stack (web frontend + API) from one terminal with prefixed, live logs.

Spec: /build/dev-launcher.md

    python scripts/dev.py                    # dev mode: web :3000 (hot reload) + API :8000 (auto-reload)
    python scripts/dev.py --single-origin    # build the web export, serve everything from the API on :8000
    python scripts/dev.py --fake             # no LLM keys: scripted fake LLM, hash embeddings, separate database
    python scripts/dev.py --check            # pre-flight checks only

Ctrl+C stops everything. Stdlib only (Python 3.9+). On Windows without a `python` command: py -3 scripts/dev.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TextIO

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "apps" / "api"
WEB_DIR = ROOT / "apps" / "web"
KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "DEEPGRAM_API_KEY")
COLORS = {"dev": "33", "api": "36", "web": "35"}  # yellow, cyan, magenta
GRACE_SECONDS = 5.0


# ------------------------------------------------------------------ plan
@dataclass
class Service:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    pre: list[Service]          # one-shot steps run to completion first (web build)
    services: list[Service]     # long-running processes
    ready: dict[str, str]       # name -> URL polled until it answers
    open_url: str               # where the user should go


def shown(cmd: list[str]) -> str:
    """Command line for log output: executable name only, not its full path."""
    return " ".join([Path(cmd[0]).name, *cmd[1:]])


def uv_command() -> list[str] | None:
    if shutil.which("uv"):
        return ["uv"]
    try:
        if subprocess.run([sys.executable, "-m", "uv", "--version"], capture_output=True).returncode == 0:
            return [sys.executable, "-m", "uv"]
    except OSError:
        pass
    return None


def make_plan(args: argparse.Namespace, uv: list[str], npm: str, environ: dict[str, str] | None = None) -> Plan:
    environ = os.environ if environ is None else environ
    api_env = {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if args.fake:  # DEV-06: fake mode never touches the real database
        api_env.update(LLM_FAKE="1", EMBEDDINGS_PROVIDER="hash")
        if "DATABASE_URL" not in environ:
            api_env["DATABASE_URL"] = f"sqlite+aiosqlite:///{(API_DIR / 'data' / 'fake.db').as_posix()}"
    serve = [*uv, "run", "voiceai", "serve", "--port", str(args.api_port)]
    api_url = f"http://localhost:{args.api_port}"

    if args.single_origin:  # DEV-02
        pre = []
        if not args.skip_build:
            pre.append(Service("web", [npm, "run", "build"], WEB_DIR, {"NEXT_PUBLIC_API_BASE": "", "NEXT_TELEMETRY_DISABLED": "1"}))
        api = Service("api", serve, API_DIR, api_env)
        return Plan(pre, [api], {"api": f"{api_url}/healthz"}, api_url)

    if not args.no_reload:
        serve.append("--reload")
    api_env["CORS_ORIGINS"] = f"http://localhost:{args.web_port},http://127.0.0.1:{args.web_port}"  # DEV-01
    api = Service("api", serve, API_DIR, api_env)
    web = Service("web", [npm, "run", "dev", "--", "-p", str(args.web_port)], WEB_DIR,
                  {"NEXT_PUBLIC_API_BASE": api_url, "NEXT_TELEMETRY_DISABLED": "1"})
    web_url = f"http://localhost:{args.web_port}"
    return Plan([], [api, web], {"api": f"{api_url}/healthz", "web": f"{web_url}/"}, web_url)


# ------------------------------------------------------------------ pre-flight
def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def preflight(
    args: argparse.Namespace, uv: list[str] | None, npm: str | None, environ: dict[str, str] | None = None,
    root: Path | None = None, in_use: Callable[[int], bool] | None = None,
) -> tuple[list[str], list[str], dict[str, bool]]:
    """Returns (errors, warnings, key_status). Never exposes key values (DEV-05, DEV-06)."""
    environ = os.environ if environ is None else environ
    root = root or ROOT
    in_use = in_use or port_in_use
    api_dir, web_dir = root / "apps" / "api", root / "apps" / "web"
    errors: list[str] = []
    warnings: list[str] = []
    fix = "run: python scripts/setup.py --install   (or add --install to this command)"

    if not uv:
        errors.append("uv not found. Install it (https://docs.astral.sh/uv/ or: python -m pip install --user uv) and open a new terminal.")
    if not npm:
        errors.append("npm not found. Install Node.js LTS (https://nodejs.org) and open a new terminal.")
    if not (api_dir / ".venv").exists():
        errors.append(f"backend dependencies are not installed (apps/api/.venv missing); {fix}")
    needs_node_modules = not args.single_origin or not args.skip_build
    if needs_node_modules and not (web_dir / "node_modules").exists():
        errors.append(f"web dependencies are not installed (apps/web/node_modules missing); {fix}")
    if args.single_origin and args.skip_build and not (web_dir / "out").exists():
        errors.append("--skip-build needs an existing build (apps/web/out missing); drop --skip-build to build it")
    ports = [args.api_port] if args.single_origin else [args.api_port, args.web_port]
    for port in ports:
        flag = "--api-port" if port == args.api_port else "--web-port"
        if in_use(port):
            errors.append(f"port {port} is already in use (another dev server running?). Stop it or pass {flag} <free port>")

    dotenv_path = api_dir / ".env"
    merged = {**read_dotenv(dotenv_path), **{k: v for k, v in environ.items() if v != ""}}
    status = {k: bool(merged.get(k)) for k in KEYS}
    if not dotenv_path.exists():
        warnings.append("apps/api/.env not found; using only the process environment (python scripts/setup.py creates it)")
    if not args.fake:
        if not status["GROQ_API_KEY"] and not status["OPENROUTER_API_KEY"]:
            warnings.append("no GROQ_API_KEY or OPENROUTER_API_KEY: agent replies will fail. Add a key to apps/api/.env, or use --fake for a UI-only run")
        elif not status["GROQ_API_KEY"] and not merged.get("LLM_ROLE_REALTIME"):
            warnings.append("only OPENROUTER_API_KEY is set: also set the five LLM_ROLE_* lines in apps/api/.env (see specs/build/runbook-local.md)")
    if not status["DEEPGRAM_API_KEY"]:
        warnings.append("no DEEPGRAM_API_KEY: the Talk tab is disabled; use Type on the Test call page")
    return errors, warnings, status


# ------------------------------------------------------------------ output
def enable_color(out: TextIO) -> bool:
    if os.environ.get("NO_COLOR") or not getattr(out, "isatty", lambda: False)():
        return False
    if os.name == "nt":
        os.system("")  # enables ANSI escape processing in the Windows console
    return True


class Printer:
    def __init__(self, out: TextIO, color: bool = False, width: int = 3) -> None:
        self.out, self.color, self.width = out, color, width
        self._lock = threading.Lock()

    def line(self, tag: str, text: str) -> None:
        label = f"[{tag}]".ljust(self.width + 2)
        if self.color:
            label = f"\033[{COLORS.get(tag, '37')}m{label}\033[0m"
        with self._lock:
            print(f"{label} {text}", file=self.out, flush=True)


# ------------------------------------------------------------------ process supervision
@dataclass
class Outcome:
    code: int
    interrupted: bool = False
    exited: str | None = None   # name of the service that ended the run


def spawn(svc: Service) -> subprocess.Popen[bytes]:
    kwargs: dict = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return subprocess.Popen(
        svc.cmd, cwd=svc.cwd, env={**os.environ, **svc.env}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs,
    )


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop a process and everything it started (DEV-04)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        for sig, wait in ((signal.SIGTERM, GRACE_SECONDS), (signal.SIGKILL, 2.0)):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def watch_ready(urls: dict[str, str], open_url: str, printer: Printer, stop: threading.Event) -> None:
    pending = dict(urls)
    deadline = time.time() + 600
    while pending and not stop.is_set() and time.time() < deadline:
        for name, url in list(pending.items()):
            try:
                urllib.request.urlopen(url, timeout=2).close()
            except Exception:  # noqa: BLE001 - not up yet (connection refused, 5xx while compiling)
                continue
            printer.line("dev", f"{name} ready  ({url})")
            del pending[name]
        stop.wait(1.0)
    if not pending and not stop.is_set():
        printer.line("dev", f"READY - open {open_url}")


def supervise(
    services: list[Service], printer: Printer, ready: dict[str, str] | None = None, open_url: str = "",
    install_signals: bool = True,
) -> Outcome:
    """Run services together, stream prefixed output, stop all when one exits or on Ctrl+C (DEV-03, DEV-04)."""
    procs: list[tuple[Service, subprocess.Popen[bytes]]] = []
    pumps: list[threading.Thread] = []
    stop = threading.Event()
    requested = threading.Event()

    def pump(svc: Service, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            printer.line(svc.name, raw.decode("utf-8", errors="replace").rstrip("\r\n"))

    previous: dict[int, object] = {}
    if install_signals and threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous[sig] = signal.signal(sig, lambda *_: requested.set())

    outcome = Outcome(0)
    try:
        for svc in services:
            proc = spawn(svc)
            procs.append((svc, proc))
            t = threading.Thread(target=pump, args=(svc, proc), daemon=True)
            t.start()
            pumps.append(t)
        if ready:
            threading.Thread(target=watch_ready, args=(ready, open_url, printer, stop), daemon=True).start()
        while not requested.is_set():
            ended = next(((s, p) for s, p in procs if p.poll() is not None), None)
            if ended:
                svc, proc = ended
                code = proc.returncode if proc.returncode and proc.returncode > 0 else (1 if proc.returncode else 0)
                outcome = Outcome(code, False, svc.name)
                break
            time.sleep(0.2)
        else:
            outcome = Outcome(0, True)
    except KeyboardInterrupt:
        outcome = Outcome(0, True)
    finally:
        stop.set()
        for _, proc in procs:
            kill_tree(proc)
        for t in pumps:
            t.join(timeout=2)
        for sig, handler in previous.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]
    return outcome


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--single-origin", action="store_true", help="build the web export and serve everything from the API (no hot reload)")
    ap.add_argument("--skip-build", action="store_true", help="with --single-origin: reuse an existing apps/web/out")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=3000)
    ap.add_argument("--no-reload", action="store_true", help="run the API without auto-reload")
    ap.add_argument("--fake", action="store_true", help="no LLM keys: fake LLM, hash embeddings, separate database (apps/api/data/fake.db)")
    ap.add_argument("--install", action="store_true", help="run scripts/setup.py --install first")
    ap.add_argument("--check", action="store_true", help="run the pre-flight checks and exit")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    printer = Printer(sys.stdout, enable_color(sys.stdout))

    if args.install:
        printer.line("dev", "installing dependencies (scripts/setup.py --install)")
        if subprocess.run([sys.executable, str(ROOT / "scripts" / "setup.py"), "--install"]).returncode != 0:
            printer.line("dev", "setup failed; fix the errors above and retry")
            return 1

    uv, npm = uv_command(), shutil.which("npm")
    errors, warnings, status = preflight(args, uv, npm)
    mode = "single-origin" if args.single_origin else "dev"
    printer.line("dev", f"Voice Agent Studio - {mode} mode" + (" (fake LLM)" if args.fake else ""))
    printer.line("dev", "keys: " + ", ".join(f"{k.replace('_API_KEY', '')} {'set' if v else 'missing'}" for k, v in status.items()))
    for w in warnings:
        printer.line("dev", f"warning: {w}")
    for e in errors:
        printer.line("dev", f"error: {e}")
    if errors:
        return 1
    plan = make_plan(args, uv, npm)  # type: ignore[arg-type]
    if args.check:
        printer.line("dev", "pre-flight ok. Would run: " + "; ".join(shown(s.cmd) for s in [*plan.pre, *plan.services]))
        return 0

    printer.width = 3
    for step in plan.pre:
        printer.line("dev", f"{step.name}: {shown(step.cmd)}   (one-time step)")
        outcome = supervise([step], printer, install_signals=True)
        if outcome.interrupted:
            return 130
        if outcome.code != 0:
            printer.line("dev", f"{step.name} step failed (exit {outcome.code}); not starting the servers")
            return outcome.code
    for svc in plan.services:
        printer.line("dev", f"{svc.name}: {shown(svc.cmd)}")
    printer.line("dev", "starting; first API start seeds the demo data (about a minute). Ctrl+C stops everything.")
    outcome = supervise(plan.services, printer, plan.ready, plan.open_url)
    if outcome.interrupted:
        printer.line("dev", "stopped.")
        return 0
    printer.line("dev", f"{outcome.exited} exited (code {outcome.code}); stopped everything.")
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
