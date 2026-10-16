#!/usr/bin/env python3
"""One command from values in apps/api/.env to a phone number an agent answers.

Spec: /build/phone-demo.md, /architecture/telephony.md

    python scripts/phone_demo.py             # tunnel + API + number mapping + Twilio webhook, then call the number
    python scripts/phone_demo.py --check     # pre-flight only: what is configured, what is missing
    python scripts/phone_demo.py --simulator # no Twilio account: the local Twilio simulator and its browser phone

Needs in apps/api/.env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, OPENAI_API_KEY; and `ngrok` or `cloudflared`
installed. Optional: DEMO_AGENT, DEMO_TRANSFER_TO, NGROK_AUTHTOKEN. Ctrl+C restores the number's previous webhook and stops everything.
Stdlib only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402  (scripts/dev.py: dotenv reader, process helpers)

ROOT = dev.ROOT
API_DIR = dev.API_DIR
REQUIRED = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "OPENAI_API_KEY")
E164 = re.compile(r"\+[1-9][0-9]{6,14}")
SIP = re.compile(r"sip:[^\s@]+@\S+")
TENANT = "evergreen-care"
DEFAULT_AGENT = "Insurance Claims Agent"
SIM_SID, SIM_TOKEN, SIM_NUMBER = "ACsimulator", "simulator-token", "+15550001111"
WEBHOOK_PATH = "/api/telephony/twilio/voice"
CLOUDFLARED_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class DemoError(Exception):
    """A problem the presenter can fix; the message says how."""


# ------------------------------------------------------------------ configuration and pre-flight (DEV-07)
def load_config(environ: dict[str, str] | None = None, dotenv: dict[str, str] | None = None) -> dict[str, str]:
    """The environment wins over apps/api/.env, like the API's own settings."""
    merged = dict(dev.read_dotenv(API_DIR / ".env") if dotenv is None else dotenv)
    merged.update({k: v for k, v in (os.environ if environ is None else environ).items() if v})
    return {k: v for k, v in merged.items() if v}


def preflight(cfg: dict[str, str], args: argparse.Namespace, which: Callable[[str], str | None] | None = None,
              uv: list[str] | None = None, in_use: Callable[[int], bool] | None = None) -> list[str]:
    """Problems with their fixes; never includes a value of a key (DEV-07, DEV-12)."""
    which = which or shutil.which
    if getattr(args, "simulator", False):  # no Twilio account, no tunnel: only the OpenAI key (DEV-12)
        problems = [] if cfg.get("OPENAI_API_KEY") else ["OPENAI_API_KEY is missing: add it to apps/api/.env"]
        if not (dev.uv_command() if uv is None else uv):
            problems.append("uv is not installed: https://docs.astral.sh/uv/")
        for port in (args.port, args.sim_port):
            if (in_use or dev.port_in_use)(port):
                problems.append(f"port {port} is busy: stop what is using it or pass --port / --sim-port")
        return problems
    problems = [f"{k} is missing: add it to apps/api/.env" for k in REQUIRED if not cfg.get(k)]
    number = cfg.get("TWILIO_PHONE_NUMBER")
    if number and not E164.fullmatch(number):
        problems.append("TWILIO_PHONE_NUMBER must be in international format, for example +15551234567")
    transfer = cfg.get("DEMO_TRANSFER_TO")
    if transfer and not (E164.fullmatch(transfer) or SIP.fullmatch(transfer)):
        problems.append("DEMO_TRANSFER_TO must be an international number such as +15557654321 or a sip: address")
    if not args.public_url and not (which("ngrok") or which("cloudflared")):
        problems.append("no tunnel tool found: install ngrok (https://ngrok.com/download, then `ngrok config add-authtoken <token>`) "
                        "or cloudflared (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/), "
                        "or pass --public-url")
    if not (dev.uv_command() if uv is None else uv):
        problems.append("uv is not installed: https://docs.astral.sh/uv/")
    if (in_use or dev.port_in_use)(args.port):
        problems.append(f"port {args.port} is busy: stop what is using it or pass --port")
    return problems


# ------------------------------------------------------------------ tunnel (DEV-08)
def pick_ngrok_url(listing: dict[str, Any]) -> str | None:
    """The https public URL from ngrok's local API (GET http://127.0.0.1:4040/api/tunnels)."""
    for tunnel in listing.get("tunnels", []):
        url = tunnel.get("public_url", "")
        if url.startswith("https://"):
            return url
    return None


def parse_cloudflared_url(line: str) -> str | None:
    m = CLOUDFLARED_URL.search(line)
    return m.group(0) if m else None


def start_tunnel(port: int, cfg: dict[str, str], which: Callable[[str], str | None] | None = None,
                 timeout: float = 40.0) -> tuple[subprocess.Popen[bytes], str]:
    which = which or shutil.which
    env = {**os.environ, **({"NGROK_AUTHTOKEN": cfg["NGROK_AUTHTOKEN"]} if cfg.get("NGROK_AUTHTOKEN") else {})}
    if which("ngrok"):
        proc = subprocess.Popen(["ngrok", "http", str(port), "--log=stdout"], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_group())
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise DemoError("ngrok exited: check that its auth token is set (`ngrok config add-authtoken <token>` or NGROK_AUTHTOKEN in .env)")
            try:
                with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
                    url = pick_ngrok_url(json.load(r))
                if url:
                    return proc, url
            except Exception:  # noqa: BLE001 - ngrok is still starting
                pass
            time.sleep(0.5)
        dev.kill_tree(proc)
        raise DemoError("ngrok did not report a public URL in time")
    proc = subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **_group())
    found: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            url = parse_cloudflared_url(raw.decode("utf-8", "replace"))
            if url:
                found.append(url)
                return

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.time() + timeout
    while time.time() < deadline and not found:
        if proc.poll() is not None:
            raise DemoError("cloudflared exited before it reported a public URL")
        time.sleep(0.3)
    if not found:
        dev.kill_tree(proc)
        raise DemoError("cloudflared did not report a public URL in time")
    return proc, found[0]


def _group() -> dict[str, Any]:
    return {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}


# ------------------------------------------------------------------ Twilio (DEV-09)
def twilio_call(cfg: dict[str, str], method: str, path: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    base = (cfg.get("TWILIO_API_BASE") or "https://api.twilio.com").rstrip("/")
    url = f"{base}/2010-04-01/Accounts/{cfg['TWILIO_ACCOUNT_SID']}{path}"
    token = base64.b64encode(f"{cfg['TWILIO_ACCOUNT_SID']}:{cfg['TWILIO_AUTH_TOKEN']}".encode()).decode()
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={"Authorization": f"Basic {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        hint = " (check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)" if exc.code in (401, 403) else ""
        raise DemoError(f"Twilio answered HTTP {exc.code}{hint}") from exc
    except urllib.error.URLError as exc:
        raise DemoError(f"cannot reach Twilio: {exc.reason}") from exc


def set_webhook(cfg: dict[str, str], voice_url: str) -> tuple[str, str]:
    """Point the number's voice webhook at `voice_url` (POST); returns (sid of the number, its previous voice URL)."""
    number = cfg["TWILIO_PHONE_NUMBER"]
    found = twilio_call(cfg, "GET", "/IncomingPhoneNumbers.json?" + urllib.parse.urlencode({"PhoneNumber": number}))
    rows = found.get("incoming_phone_numbers") or []
    if not rows:
        raise DemoError(f"{number} is not a phone number of this Twilio account: check TWILIO_PHONE_NUMBER and the account SID")
    row = rows[0]
    twilio_call(cfg, "POST", f"/IncomingPhoneNumbers/{row['sid']}.json", {"VoiceUrl": voice_url, "VoiceMethod": "POST"})
    return row["sid"], row.get("voice_url") or ""


def restore_webhook(cfg: dict[str, str], number_sid: str, previous: str) -> None:
    twilio_call(cfg, "POST", f"/IncomingPhoneNumbers/{number_sid}.json", {"VoiceUrl": previous, "VoiceMethod": "POST"})


# ------------------------------------------------------------------ the app's own API (DEV-10)
Request = Callable[[str, str, Any], tuple[int, Any]]


def http_request(base: str, tenant: str = TENANT) -> Request:
    def request(method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-Tenant-Id": tenant, **({"Content-Type": "application/json"} if data is not None else {})}
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, (json.loads(raw) if raw else None)

    return request


def _ok(status: int, body: Any, what: str) -> Any:
    if status >= 400:
        detail = (body or {}).get("detail") if isinstance(body, dict) else ""
        raise DemoError(f"{what} failed (HTTP {status}{': ' + detail if detail else ''})")
    return body


def setup_agent(request: Request, agent_name: str, number: str, transfer_to: str | None = None) -> list[str]:
    """Map `number` to the agent and set its transfer number; idempotent. Returns what was done."""
    done: list[str] = []
    agents = _ok(*request("GET", "/api/agents", None), "listing agents")["items"]
    agent = next((a for a in agents if a["name"] == agent_name), None)
    if agent is None:
        names = ", ".join(a["name"] for a in agents)
        raise DemoError(f"no agent named '{agent_name}': set DEMO_AGENT to one of: {names}")
    if not agent.get("published_version"):
        raise DemoError(f"agent '{agent_name}' is not published")
    mapped = _ok(*request("GET", "/api/phone-numbers", None), "listing phone numbers")["items"]
    current = next((n for n in mapped if n["e164"] == number), None)
    if current and current["agent_id"] != agent["id"]:
        _ok(*request("DELETE", f"/api/phone-numbers/{current['id']}", None), "re-mapping the number")
        current = None
        done.append(f"{number} was mapped to another agent: re-mapped")
    if current is None:
        _ok(*request("POST", "/api/phone-numbers", {"e164": number, "agent_id": agent["id"], "label": "phone demo"}), "mapping the number")
        done.append(f"{number} -> {agent_name}")
    if transfer_to:
        draft = _ok(*request("GET", f"/api/agents/{agent['id']}", None), "reading the agent")["draft_config"]
        if (draft.get("telephony") or {}).get("transfer_to") != transfer_to:
            draft["telephony"] = {**(draft.get("telephony") or {}), "transfer_to": transfer_to}
            _ok(*request("PUT", f"/api/agents/{agent['id']}", {"draft_config": draft}), "saving the transfer number")
            _ok(*request("POST", f"/api/agents/{agent['id']}/publish", {"change_note": "Phone demo: transfer number"}), "publishing the agent")
            done.append(f"transfer number {transfer_to} saved and published")
    return done


# ------------------------------------------------------------------ simulator mode (DEV-12)
def simulator_plan(args: argparse.Namespace, uv: list[str]) -> list[tuple[str, list[str], Path, dict[str, str]]]:
    """The simulator and the API, wired together: same account, token and number; the API's Twilio base URL is the simulator."""
    api_url = f"http://127.0.0.1:{args.port}"
    shared = {"TWILIO_ACCOUNT_SID": SIM_SID, "TWILIO_AUTH_TOKEN": SIM_TOKEN, "TWILIO_PHONE_NUMBER": SIM_NUMBER, "PUBLIC_BASE_URL": api_url}
    sim_env = {**shared, "SIM_PORT": str(args.sim_port), "SIM_PLATFORM_URL": api_url}
    api_env = {**shared, "TWILIO_API_BASE": f"http://127.0.0.1:{args.sim_port}"}
    return [
        ("simulator", [*uv, "run", "python", "../../scripts/twilio_sim.py"], API_DIR, sim_env),
        ("api", [*uv, "run", "voiceai", "serve", "--port", str(args.port)], API_DIR, api_env),
    ]


def run_simulator(args: argparse.Namespace, cfg: dict[str, str]) -> int:
    say = lambda text: print(f"[demo] {text}", flush=True)  # noqa: E731
    procs: list[subprocess.Popen[bytes]] = []
    try:
        log_dir = API_DIR / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        for name, cmd, cwd, env in simulator_plan(args, dev.uv_command() or ["uv"]):
            say(f"starting the {name} (log: apps/api/data/phone-demo-{name}.log) ...")
            log = open(log_dir / f"phone-demo-{name}.log", "wb")  # noqa: SIM115 - lives as long as the process
            procs.append(subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **env}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **_group()))
            wait_for(f"http://127.0.0.1:{args.sim_port if name == 'simulator' else args.port}/{'sim/state' if name == 'simulator' else 'healthz'}", procs[-1])
        request = http_request(f"http://127.0.0.1:{args.port}")
        for line in setup_agent(request, cfg.get("DEMO_AGENT") or DEFAULT_AGENT, SIM_NUMBER, cfg.get("DEMO_TRANSFER_TO")) or ["already set up"]:
            say(line)
        sim_cfg = {"TWILIO_ACCOUNT_SID": SIM_SID, "TWILIO_AUTH_TOKEN": SIM_TOKEN, "TWILIO_PHONE_NUMBER": SIM_NUMBER,
                   "TWILIO_API_BASE": f"http://127.0.0.1:{args.sim_port}"}
        set_webhook(sim_cfg, f"http://127.0.0.1:{args.port}{WEBHOOK_PATH}")
        print("\n" + "=" * 64)
        print("  READY (Twilio simulator, no Twilio account needed)")
        print(f"  Open the browser phone:  http://localhost:{args.sim_port}   (use a headset)")
        print(f"  Dial {SIM_NUMBER}, or pick an outbound agent and press 'Call me'")
        print(f"  Calls page: http://localhost:{args.port}/calls/   |   Ctrl+C stops everything")
        print("=" * 64 + "\n", flush=True)
        seen: dict[str, str] = {}
        feed_calls(request, seen, lambda _: None)
        while True:
            time.sleep(2)
            for proc in procs:
                if proc.poll() is not None:
                    raise DemoError("a process stopped: see the logs in apps/api/data/phone-demo-*.log")
            feed_calls(request, seen, say)
    except KeyboardInterrupt:
        print()
        return 0
    except DemoError as exc:
        print(f"\nproblem: {exc}", file=sys.stderr)
        return 1
    finally:
        for proc in reversed(procs):
            dev.kill_tree(proc)


# ------------------------------------------------------------------ run
def wait_for(url: str, proc: subprocess.Popen[bytes], timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise DemoError("the API exited while starting: see apps/api/data/phone-demo-api.log")
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return
        except Exception:  # noqa: BLE001 - still starting (the first start seeds the demo data)
            time.sleep(1)
    raise DemoError("the API did not start in time: see apps/api/data/phone-demo-api.log")


def feed_calls(request: Request, seen: dict[str, str], say: Callable[[str], None]) -> None:
    status, body = request("GET", "/api/calls?include_seed=false", None)
    if status != 200:
        return
    for call in reversed(body["items"]):
        state = call["status"] if not call.get("outcome") else f"{call['status']} ({call['outcome']})"
        if seen.get(call["id"]) != state:
            seen[call["id"]] = state
            who = "phone" if call.get("transport") == "phone" else call["channel"]
            say(f"call {call['id'][:8]} [{who}] {state}  turns={call['turn_count']}  cost=${call['llm_cost_usd']:.4f}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--public-url", default=None, help="use this public URL instead of starting a tunnel")
    p.add_argument("--keep-webhook", action="store_true", help="do not restore the number's previous webhook on exit")
    p.add_argument("--check", action="store_true", help="pre-flight only")
    p.add_argument("--simulator", action="store_true", help="no Twilio account: start the local Twilio simulator and its browser phone")
    p.add_argument("--sim-port", type=int, default=9200, help="simulator port (with --simulator)")
    args = p.parse_args(argv)
    if hasattr(signal, "SIGTERM"):  # a stopped demo cleans up like Ctrl+C: restores the webhook and stops the processes
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    cfg = load_config()
    if cfg.get("PUBLIC_BASE_URL") and not args.public_url:
        print("note: PUBLIC_BASE_URL in .env is ignored; this script sets it from the tunnel")
    problems = preflight(cfg, args)
    print("Phone demo pre-flight" + (" (simulator)" if args.simulator else ""))
    for key in (("OPENAI_API_KEY",) if args.simulator else REQUIRED):
        print(f"  {'ok     ' if cfg.get(key) else 'MISSING'} {key}")
    if not args.simulator:
        print(f"  tunnel   {'--public-url' if args.public_url else ('ngrok' if shutil.which('ngrok') else ('cloudflared' if shutil.which('cloudflared') else 'MISSING'))}")
    for problem in problems:
        print(f"  problem: {problem}")
    if problems:
        return 2
    if args.check:
        print("everything is in place; run without --check to start")
        return 0
    if args.simulator:
        return run_simulator(args, cfg)

    procs: list[subprocess.Popen[bytes]] = []
    restore: tuple[str, str] | None = None
    say = lambda text: print(f"[demo] {text}", flush=True)  # noqa: E731
    try:
        if args.public_url:
            public = args.public_url.rstrip("/")
        else:
            say("starting the tunnel ...")
            tunnel, public = start_tunnel(args.port, cfg)
            procs.append(tunnel)
        say(f"public URL {public}")
        log_path = API_DIR / "data" / "phone-demo-api.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        say(f"starting the API on :{args.port} (log: {log_path.relative_to(ROOT)}) ...")
        log = open(log_path, "wb")  # noqa: SIM115 - lives as long as the API
        api = subprocess.Popen([*dev.uv_command(), "run", "voiceai", "serve", "--port", str(args.port)], cwd=API_DIR,
                               env={**os.environ, "PUBLIC_BASE_URL": public}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **_group())
        procs.append(api)
        wait_for(f"http://127.0.0.1:{args.port}/healthz", api)
        request = http_request(f"http://127.0.0.1:{args.port}")
        for line in setup_agent(request, cfg.get("DEMO_AGENT") or DEFAULT_AGENT, cfg["TWILIO_PHONE_NUMBER"], cfg.get("DEMO_TRANSFER_TO")) or ["already set up"]:
            say(line)
        sid, previous = set_webhook(cfg, public + WEBHOOK_PATH)
        restore = None if args.keep_webhook else (sid, previous)
        say(f"Twilio number {cfg['TWILIO_PHONE_NUMBER']} now calls {public}{WEBHOOK_PATH}")
        print("\n" + "=" * 64)
        print(f"  READY - call {cfg['TWILIO_PHONE_NUMBER']} now")
        print("  (a Twilio trial plays a notice first and only takes calls from verified numbers)")
        print(f"  Calls page: http://localhost:{args.port}/calls/   |   Ctrl+C stops and restores the webhook")
        print("=" * 64 + "\n", flush=True)
        seen: dict[str, str] = {}
        feed_calls(request, seen, lambda _: None)  # calls from before this run are not news
        while True:
            time.sleep(2)
            if api.poll() is not None:
                raise DemoError("the API stopped: see apps/api/data/phone-demo-api.log")
            feed_calls(request, seen, say)
    except KeyboardInterrupt:
        print()
        return 0
    except DemoError as exc:
        print(f"\nproblem: {exc}", file=sys.stderr)
        return 1
    finally:
        if restore:
            try:
                restore_webhook(cfg, *restore)
                say("restored the number's previous webhook")
            except DemoError as exc:
                print(f"could not restore the webhook ({exc}); set it back in the Twilio console", file=sys.stderr)
        for proc in reversed(procs):
            dev.kill_tree(proc)


if __name__ == "__main__":
    sys.exit(main())
