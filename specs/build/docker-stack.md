---
type: Tool Spec
title: Docker stack
description: scripts/docker_stack.py - builds infra/Dockerfile and runs the web app, the API and the dental demo mock in one local container against the local database and .env; the way to get voice on machines whose policy blocks the voice pipeline's native libraries.
status: stable
tags: [build, tooling, dx, docker]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

The voice pipelines import native libraries (for example `sentencex`). Windows Application Control can block them, and the `voiceai.exe` launcher, on a managed laptop; every Talk call then drops with no events. A Linux container is not subject to that policy. [CP-0038](/changes/cp-0038-one-start-for-demo-mock-and-docker.md).

# Usage

```bash
python scripts/docker_stack.py start              # build voiceai:local, run it on http://localhost:8080
python scripts/docker_stack.py start --skip-build # reuse the last image
python scripts/docker_stack.py start --port 9090  # another host port
python scripts/docker_stack.py status | logs [-f] | stop
```

Stdlib only; needs Docker (Docker Desktop on Windows and macOS) with its engine running.

# Behavior

1. **Pre-flight.** Errors exit 1 and start nothing: `docker` not found or its engine not answering; `apps/api/.env` missing; the host port in use by anything other than this container; a local API answering `http://127.0.0.1:8000/healthz` (a `dev.py` stack), because both would write `apps/api/data/voiceai.db` over a Docker mount, unless `--force`.
2. **Build** (unless `--skip-build`): `docker build -f infra/Dockerfile -t voiceai:local .` from the repo root. The image is the Cloud Run image ([/architecture/deployment.md](/architecture/deployment.md)) and also holds `scripts/demo/dental_mock.py`.
3. **Run**: an existing `voiceai-local` container is removed first, then `docker run -d --name voiceai-local -p <port>:8080` with:
   * `apps/api/data` mounted at `/app/apps/api/data`, so the container uses the local database (`voiceai.db`) and its agents;
   * the variables of `apps/api/.env`, quotes stripped, written to a temporary env file passed with `--env-file` and deleted after the container starts; no value is printed;
   * the command `python3 /app/scripts/demo/dental_mock.py --port 8766 & exec uv run --no-sync voiceai serve --host 0.0.0.0 --port 8080`, so the dental tools' `http://127.0.0.1:8766` URLs reach the mock inside the container. `--no-mock` leaves the mock out.
4. **Readiness**: polls `http://localhost:<port>/healthz` (the first start may seed data and take about a minute), then prints `READY - open http://localhost:<port>`. On timeout it prints the last container log lines and exits 1, leaving the container for `logs`.
5. **status** prints whether the container runs, its port and `/healthz`; **logs** runs `docker logs` (`-f` follows, `-n` lines); **stop** removes the container. The image and the database stay.

The web app is served by the API on the same origin, as on Cloud Run: there is no hot reload; run `start` again after code changes.

# Acceptance

- **DEV-15** — Given `docker_stack.py start` with defaults, when its plan is built, then it builds `voiceai:local` from `infra/Dockerfile`, runs container `voiceai-local` publishing host `8080` to the container's `8080`, mounts `apps/api/data` at `/app/apps/api/data`, passes the variables of `apps/api/.env` (quotes stripped) without printing any value, and starts `dental_mock.py --port 8766` inside the container before the API; `--skip-build` drops the build and `--port 9090` publishes 9090.
- **DEV-16** — Given a local API answering `/healthz` on `:8000`, when `docker_stack.py start` runs without `--force`, then it exits 1 naming the reason and starts nothing.
- **DEV-17** — Given the container running, then `http://localhost:8080/healthz` is `ok`, a Talk call to a published voice agent connects (checked by hand on the owner's laptop), and a dental tool call reaches the mock inside the container.
