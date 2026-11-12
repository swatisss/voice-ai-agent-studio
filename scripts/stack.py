#!/usr/bin/env python3
"""Start, stop and inspect the whole stack in the background, with the LLM and decision model you choose.

Wraps scripts/dev.py (Spec: /build/dev-launcher.md): `start` runs it detached, logs to
apps/api/data/stack/stack.log and returns once the stack answers; `stop` ends its whole process tree.

    python scripts/stack.py start                                   # models from config/models.yaml and apps/api/.env
    python scripts/stack.py start --llm openai:gpt-4.1-mini         # every chat role on one exact model
    python scripts/stack.py start --role realtime=groq:openai/gpt-oss-120b --role judge=openai:gpt-4.1-mini
    python scripts/stack.py start --decision-model https://api.typesafe.ai --decision-name jev-latest
    python scripts/stack.py start --fake                            # scripted fake LLM: no keys, no cost
    python scripts/stack.py status                                  # pid, health, the model each role uses, routing mode
    python scripts/stack.py logs [-n 100] [-f]
    python scripts/stack.py stop                                    # add --force to also free the ports

Model refs are `provider:model` keys from apps/api/config/models.yaml. Fallbacks listed there still apply
when the chosen model fails; `status` shows the primary model per role. Keys stay in apps/api/.env
(DECISION_MODEL_API_KEY too); this script never prints a key value. Stdlib only.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402  - the launcher this script supervises

ROOT = dev.ROOT
STATE_DIR = dev.API_DIR / "data" / "stack"
STATE_FILE = STATE_DIR / "stack.json"
LOG_FILE = STATE_DIR / "stack.log"
MODELS_YAML = dev.API_DIR / "config" / "models.yaml"
CHAT_ROLES = ("realtime", "analysis", "drafting", "simulator", "judge", "turn", "router")
ROUTING_MODES = ("embedding", "decision_model")


# ------------------------------------------------------------------ models and environment
def model_refs(path: Path = MODELS_YAML) -> dict[str, bool]:
    """`provider:model` refs under `models:` -> whether each is a speech model (no YAML dependency)."""
    refs: dict[str, bool] = {}
    in_models = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\S", line):
            in_models = line.startswith("models:")
            continue
        m = re.match(r'^\s+"([^"]+)":\s*\{(.*)\}', line) if in_models else None
        if m:
            refs[m.group(1)] = "kind: speech" in m.group(2)
    return refs


def role_overrides(args: argparse.Namespace, refs: dict[str, bool]) -> tuple[dict[str, str], list[str]]:
    """LLM_ROLE_* variables for the chosen models; errors for unknown roles, unknown refs or the wrong kind."""
    env: dict[str, str] = {}
    errors: list[str] = []
    if args.llm:
        env.update({f"LLM_ROLE_{r.upper()}": args.llm for r in CHAT_ROLES})
    for item in args.role or []:
        role, sep, ref = item.partition("=")
        role = role.strip().lower()
        if not sep or role not in (*CHAT_ROLES, "speech"):
            errors.append(f"--role {item!r}: use ROLE=provider:model, ROLE one of {', '.join((*CHAT_ROLES, 'speech'))}")
            continue
        env[f"LLM_ROLE_{role.upper()}"] = ref.strip()
    if args.speech:
        env["LLM_ROLE_SPEECH"] = args.speech
    for var, ref in env.items():
        speech_role = var == "LLM_ROLE_SPEECH"
        if ref not in refs:
            errors.append(f"{ref!r} is not in apps/api/config/models.yaml; known: {', '.join(r for r, s in refs.items() if s == speech_role)}")
        elif refs[ref] != speech_role:
            errors.append(f"{var}: {ref!r} is {'a speech' if refs[ref] else 'a chat'} model; "
                          + ("the speech role needs a speech model" if speech_role else "chat roles need a chat model"))
    return env, errors


def decision_env(args: argparse.Namespace) -> dict[str, str]:
    pairs = {
        "DECISION_MODEL_URL": args.decision_model, "DECISION_MODEL_NAME": args.decision_name,
        "DECISION_MODEL_THRESHOLD": args.decision_threshold, "DECISION_MODEL_HOSTED": args.decision_hosted,
        "DECISION_MODEL_TIMEOUT_VOICE_MS": args.decision_timeout_voice_ms, "DECISION_MODEL_TIMEOUT_TEXT_MS": args.decision_timeout_text_ms,
    }
    return {k: str(v) for k, v in pairs.items() if v is not None}


# ------------------------------------------------------------------ state and processes
def read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    import signal

    for sig, wait in ((signal.SIGTERM, dev.GRACE_SECONDS), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pid, sig)  # started with start_new_session: the group is dev.py and everything it runs
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.time() + wait
        while time.time() < deadline and alive(pid):
            time.sleep(0.2)
        if not alive(pid):
            return


def listeners(port: int) -> set[int]:
    """PIDs listening on a local TCP port (for --force)."""
    pids: set[int] = set()
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
                pids.add(int(parts[4]))
    else:
        out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        pids.update(int(p) for p in out.split() if p.isdigit())
    pids.discard(0)
    return pids


def get_json(url: str | urllib.request.Request, opener: urllib.request.OpenerDirector | None = None, timeout: float = 3) -> dict | None:
    try:
        with (opener or urllib.request.build_opener()).open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def wait_ready(urls: list[str], pid: int, timeout: float) -> bool:
    pending = list(urls)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        if not alive(pid):
            return False
        for url in list(pending):
            try:
                urllib.request.urlopen(url, timeout=2).close()
                pending.remove(url)
            except Exception:  # noqa: BLE001 - not up yet
                pass
        if pending:
            time.sleep(1.0)
    return not pending


# ------------------------------------------------------------------ API calls
def studio_opener(api: str) -> urllib.request.OpenerDirector:
    """An opener signed in as the admin when Studio sign-in is on (STUDIO_ADMIN_PASSWORD), else a plain one."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    password = os.environ.get("STUDIO_ADMIN_PASSWORD") or dev.read_dotenv(dev.API_DIR / ".env").get("STUDIO_ADMIN_PASSWORD")
    if password:
        body = json.dumps({"email": "admin@echomind.test", "password": password}).encode()
        req = urllib.request.Request(f"{api}/api/auth/login", body, {"Content-Type": "application/json"}, method="POST")
        try:
            opener.open(req, timeout=10).close()
        except urllib.error.URLError as exc:
            print(f"[stack] warning: admin sign-in failed ({exc}); routing mode may not be set")
    return opener


def tenant_ids(api: str, opener: urllib.request.OpenerDirector, only: str | None = None) -> list[str]:
    if only:
        return [only]
    return [t["id"] for t in (get_json(f"{api}/api/tenants", opener) or {}).get("items", [])]


def set_routing_mode(api: str, mode: str, only: str | None = None) -> dict[str, str]:
    """Front desk routing mode is a per-tenant setting: set it for every tenant (or just `only`)."""
    opener = studio_opener(api)
    done: dict[str, str] = {}
    for tid in tenant_ids(api, opener, only):
        req = urllib.request.Request(f"{api}/api/tenant-settings/front-desk", json.dumps({"routing_mode": mode}).encode(),
                                     {"Content-Type": "application/json", "X-Tenant-Id": tid}, method="PUT")
        try:
            with opener.open(req, timeout=10) as r:
                done[tid] = json.loads(r.read().decode("utf-8")).get("routing_mode")
        except urllib.error.HTTPError as exc:
            print(f"[stack] warning: tenant {tid}: could not set routing mode: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:200]}")
        except (OSError, ValueError) as exc:
            print(f"[stack] warning: tenant {tid}: could not set routing mode: {exc}")
    return done


def print_status(state: dict) -> None:
    api = state["api_url"]
    health = get_json(f"{api}/healthz")
    print(f"[stack] pid {state['pid']} ({'running' if alive(state['pid']) else 'not running'}), started {state['started']}, mode {state['mode']}")
    print(f"[stack] open {state['open_url']}   log {LOG_FILE}")
    if not health:
        print(f"[stack] API not answering at {api}/healthz")
        return
    providers = ", ".join(f"{k} {'on' if v else 'off'}" for k, v in (health.get("providers") or {}).items())
    print(f"[stack] health {health.get('status')}; providers: {providers}")
    if state.get("fake"):
        print("[stack] LLM: fake (scripted, no network calls)")
    models = get_json(f"{api}/api/models", studio_opener(api)) or {}
    for role, ref in (models.get("roles") or {}).items():
        pinned = " (set by stack start)" if f"LLM_ROLE_{role.upper()}" in state.get("roles", {}) else ""
        print(f"[stack]   {role:<10} {ref}{pinned}")
    opener = studio_opener(api)
    router = (health.get("router") or {}).get("decision_model") or {}
    print(f"[stack] decision model: {'configured' if router.get('configured') else 'not configured'}"
          + (f", hosted {router.get('hosted')}, blocked {router.get('blocked')}, timeouts {router.get('timeouts_ms')}" if router.get("configured") else ""))
    for tid in tenant_ids(api, opener):
        req = urllib.request.Request(f"{api}/api/tenant-settings/front-desk", headers={"X-Tenant-Id": tid})
        fd = get_json(req, opener) or {}  # type: ignore[arg-type]
        print(f"[stack]   tenant {tid:<12} routing {fd.get('routing_mode', '?')}")


# ------------------------------------------------------------------ commands
def cmd_start(args: argparse.Namespace) -> int:
    state = read_state()
    if state and alive(state["pid"]):
        print(f"[stack] already running (pid {state['pid']}, {state['open_url']}). Run: python scripts/stack.py stop")
        return 1
    if args.fake and (args.llm or args.role or args.speech):
        print("[stack] error: --fake uses the scripted fake LLM; drop --llm/--role/--speech or drop --fake")
        return 1
    roles, errors = role_overrides(args, model_refs())
    for e in errors:
        print(f"[stack] error: {e}")
    if errors:
        return 1
    decision = decision_env(args)
    routing = args.routing or ("decision_model" if args.decision_model else None)
    if routing == "decision_model" and not (args.decision_model or os.environ.get("DECISION_MODEL_URL")
                                            or dev.read_dotenv(dev.API_DIR / ".env").get("DECISION_MODEL_URL")):
        print("[stack] error: --routing decision_model needs --decision-model URL (or DECISION_MODEL_URL in apps/api/.env)")
        return 1

    cmd = [sys.executable, str(ROOT / "scripts" / "dev.py"), "--api-port", str(args.api_port), "--web-port", str(args.web_port)]
    cmd += [f for f, on in (("--single-origin", args.single_origin), ("--skip-build", args.skip_build),
                            ("--no-reload", args.no_reload), ("--fake", args.fake)) if on]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "w", encoding="utf-8")  # noqa: SIM115 - handed to the child
    env = {**os.environ, **roles, **decision, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "NO_COLOR": "1"}
    kwargs: dict = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt" else {"start_new_session": True})
    popen = dict(cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    try:  # Windows: leave the caller's job object too, so closing the calling terminal or tool does not end the stack
        proc = subprocess.Popen(cmd, **popen, **{**kwargs, "creationflags": kwargs["creationflags"] | 0x01000000} if os.name == "nt" else kwargs)
    except OSError:  # the job forbids breakaway
        proc = subprocess.Popen(cmd, **popen, **kwargs)
    log.close()

    api_url = f"http://localhost:{args.api_port}"
    open_url = api_url if args.single_origin else f"http://localhost:{args.web_port}"
    state = {"pid": proc.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "api_url": api_url, "open_url": open_url,
             "ports": [args.api_port] if args.single_origin else [args.api_port, args.web_port],
             "mode": "single-origin" if args.single_origin else "dev", "fake": args.fake, "roles": roles,
             "decision_model": {k: v for k, v in decision.items()}, "routing_mode": routing}
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"[stack] started dev.py (pid {proc.pid}); log {LOG_FILE}")
    for var, ref in roles.items():
        print(f"[stack]   {var}={ref}")
    for var, val in decision.items():
        print(f"[stack]   {var}={val}")

    urls = [f"{api_url}/healthz"] + ([] if args.single_origin else [f"{open_url}/"])
    print(f"[stack] waiting for the stack (up to {args.timeout}s; the first start seeds demo data)...")
    if not wait_ready(urls, proc.pid, args.timeout):
        running = alive(proc.pid)
        print(f"[stack] {'not ready in time' if running else 'dev.py exited'}; last log lines:")
        for line in tail(LOG_FILE, 25):
            print(f"  {line}")
        if not running:
            STATE_FILE.unlink(missing_ok=True)
        return 1
    if routing:
        for tid, got in set_routing_mode(api_url, routing, args.tenant).items():
            print(f"[stack] tenant {tid}: routing mode set to {got}")
    print_status(state)
    print("[stack] READY. Stop with: python scripts/stack.py stop")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    state = read_state()
    if state and alive(state["pid"]):
        kill_pid_tree(state["pid"])
        print(f"[stack] stopped pid {state['pid']} and its process tree")
    elif state:
        print(f"[stack] pid {state['pid']} was not running")
    else:
        print("[stack] no stack started by this script")
    if args.force:
        ports = (state or {}).get("ports") or [args.api_port, args.web_port]
        for port in ports:
            for pid in listeners(port):
                if os.name == "nt":
                    kill_pid_tree(pid)
                else:
                    os.kill(pid, 15)
                print(f"[stack] --force: stopped pid {pid} listening on port {port}")
    else:
        busy = [p for p in ((state or {}).get("ports") or [args.api_port, args.web_port]) if dev.port_in_use(p)]
        if busy:
            print(f"[stack] port(s) {', '.join(map(str, busy))} still in use (another server?). Free them with: python scripts/stack.py stop --force")
    STATE_FILE.unlink(missing_ok=True)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = read_state()
    if not state:
        print("[stack] not started by this script (python scripts/stack.py start)")
        return 1
    print_status(state)
    return 0 if alive(state["pid"]) else 1


def tail(path: Path, n: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def cmd_logs(args: argparse.Namespace) -> int:
    for line in tail(LOG_FILE, args.lines):
        print(line)
    if not args.follow:
        return 0
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while True:
                line = fh.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    except OSError:
        print(f"[stack] no log at {LOG_FILE}")
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    st = sub.add_parser("start", help="start the stack in the background")
    st.add_argument("--llm", metavar="REF", help="one model ref for every chat role, e.g. openai:gpt-4.1-mini")
    st.add_argument("--role", action="append", metavar="ROLE=REF", help="model for one role (repeatable), e.g. judge=openai:gpt-4.1-mini")
    st.add_argument("--speech", metavar="REF", help="speech-to-speech model for realtime agents, e.g. openai:gpt-realtime-2.1")
    st.add_argument("--decision-model", metavar="URL", help="Jev-compatible decision model server; also switches routing to decision_model")
    st.add_argument("--decision-name", metavar="NAME", help="model name sent to the decision model, e.g. jev-latest")
    st.add_argument("--decision-threshold", type=float, metavar="X", help="confidence needed to route (default 0.55)")
    st.add_argument("--decision-hosted", choices=("0", "1"), help="1 = hosted (blocked in PHI mode), 0 = self-hosted")
    st.add_argument("--decision-timeout-voice-ms", type=int, metavar="MS")
    st.add_argument("--decision-timeout-text-ms", type=int, metavar="MS")
    st.add_argument("--routing", choices=ROUTING_MODES, help="set the front desk routing mode once the stack is up")
    st.add_argument("--tenant", metavar="ID", help="with --routing: only this tenant (default: every tenant)")
    st.add_argument("--fake", action="store_true", help="scripted fake LLM, hash embeddings, apps/api/data/fake.db")
    st.add_argument("--single-origin", action="store_true", help="build the web export and serve everything from the API")
    st.add_argument("--skip-build", action="store_true")
    st.add_argument("--no-reload", action="store_true")
    st.add_argument("--timeout", type=int, default=300, help="seconds to wait for readiness (default 300)")
    for p in (st, sp := sub.add_parser("stop", help="stop the stack and everything it started")):
        p.add_argument("--api-port", type=int, default=8000)
        p.add_argument("--web-port", type=int, default=3000)
    sp.add_argument("--force", action="store_true", help="also stop whatever still listens on the stack's ports")
    sub.add_parser("status", help="pid, health, models per role, routing mode")
    lg = sub.add_parser("logs", help="print the stack log")
    lg.add_argument("-n", "--lines", type=int, default=60)
    lg.add_argument("-f", "--follow", action="store_true")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    return {"start": cmd_start, "stop": cmd_stop, "status": cmd_status, "logs": cmd_logs}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
