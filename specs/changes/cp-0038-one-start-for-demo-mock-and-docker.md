---
type: Change Proposal
title: CP-0038 One start for the stack, the dental mock and a Docker run
description: dev.py also serves the dental demo mock so the dental agent's tools work from the first start; demo_kits.py reuses a running mock; scripts/docker_stack.py runs the whole stack plus the mock in one container, where voice works on locked-down Windows machines.
status: stable
cp_state: implemented
tags: [build, tooling, dx, demo]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

* The *Oakhaven Dental Assistant*'s booking, cover and claim tools call the mock patient system `scripts/demo/dental_mock.py` on `http://127.0.0.1:8766`. It runs only while `python scripts/demo_kits.py dental` is held open in a second terminal, so after a normal `python scripts/dev.py` those tools fail with `connection_error` (seen on 2026-11-12).
* On the owner's laptop, Windows Application Control blocks the native library `sentencex` that the voice pipelines import (`DLL load failed ... An Application Control policy has blocked this file`) and the `voiceai.exe` launcher. Every Talk call is admitted and then dies with no events (three dental calls on 2026-11-12). A Linux container is not subject to that policy, and `infra/Dockerfile` already builds the whole app, but there is no one-command way to run it locally against the local database, `.env` and the dental mock.

# What changes

* **`dev.py` starts a third service, `mock`**: `python scripts/demo/dental_mock.py --port 8766` (port `--mock-port`, default 8766), tagged `[mock]`, supervised and stopped like the others. `--no-mock` leaves it out. A busy mock port is a **warning**, not an error: if the port already answers `GET /dental/health` (for example `demo_kits.py` is serving it), the launcher reuses it; if something else holds it, the launcher warns that the dental tools will fail and starts without the mock.
* **`demo_kits.py dental` reuses a running mock**: when `--mock-port` already answers `GET /dental/health`, the kit uses it and starts none, so running the kit after `dev.py` keeps the tools' URLs on 8766. Today it falls back to a random free port, which would point the tools at a port that disappears when the script stops.
* **New `scripts/docker_stack.py start|stop|status|logs`**: builds `infra/Dockerfile` as `voiceai:local` (`--skip-build` to reuse), runs container `voiceai-local` with the web app and API on one origin at `http://localhost:8080` (`--port`), the local database folder `apps/api/data` mounted, `apps/api/.env` passed in, and the dental mock started inside the same container on 8766 so the tools' `127.0.0.1:8766` URLs resolve there. It refuses to start while a local API answers on `:8000` (two processes writing one SQLite file over a Docker mount risks corrupting it), unless `--force`.
* The image also carries `scripts/demo/dental_mock.py` (stdlib only).

# Affected specs

* [/build/dev-launcher.md](/build/dev-launcher.md) - the `mock` service, `--no-mock`, `--mock-port`, busy-port rule; DEV-12, DEV-13, DEV-14 (demo_kits reuse)
* [/build/docker-stack.md](/build/docker-stack.md) - **new**: the Docker launcher; DEV-15, DEV-16, DEV-17
* [/build/runbook-local.md](/build/runbook-local.md) - the mock starts with the stack; the Docker route when voice is blocked
* [/architecture/deployment.md](/architecture/deployment.md) - the image also holds the dental mock script (not started on Cloud Run)

# Acceptance criteria

New, in [/build/dev-launcher.md](/build/dev-launcher.md): **DEV-12** (the `mock` service in the plan), **DEV-13** (busy or already-served mock port is never an error), **DEV-14** (`demo_kits.py` reuses a running mock). New, in [/build/docker-stack.md](/build/docker-stack.md): **DEV-15** (the Docker plan), **DEV-16** (refuses while a local API runs), **DEV-17** (voice and dental tools work in the container; checked by hand). DEV-01…DEV-06 keep passing.

# Tasks

1. Spec edits (this CP).
2. `scripts/dev.py`: `mock` service, `--no-mock`, `--mock-port`, busy-port rule — covers DEV-12, DEV-13; tests in `apps/api/tests/test_dev_launcher.py`.
3. `scripts/demo_kits.py`: reuse a running mock — covers DEV-14.
4. `infra/Dockerfile`: copy `scripts/demo/dental_mock.py`; `scripts/docker_stack.py` — covers DEV-15, DEV-16; tests on the plan only (no Docker in unit tests).
5. Runbook and deployment notes; manual check DEV-17 on the owner's laptop, recorded in `scripts/acceptance-baseline.txt` with the owner's approval.

# Risks and rollout

* The mock adds a third process to every `dev.py` start; it is stdlib, starts in well under a second and holds no data (its records reset on each start, as today).
* A Docker run and a local `dev.py` share `apps/api/data/voiceai.db`; the refusal in DEV-16 is the guard. `--fake` stays a `dev.py` feature.
* The container uses the keys in `apps/api/.env`; real calls cost money as on the local stack.
* Cloud Run is unchanged: the mock script is in the image but never started there.

# Out of scope

* Starting the SafeTrip kit or building either kit automatically (`demo_kits.py` stays the way to build them).
* Hot reload inside the container (rebuild with `docker_stack.py start` after code changes).
* Fixing Windows Application Control itself (an IT allow-list for `apps/api/.venv` makes the local stack voice-capable again).
