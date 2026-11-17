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
python scripts/docker_stack.py start              # build and run everything: app on http://localhost:8080, chat on http://localhost:3100
python scripts/docker_stack.py start --skip-build # reuse the last image
python scripts/docker_stack.py start --port 9090  # another host port
python scripts/docker_stack.py start --no-chat    # without the customer chat app; also --no-login, --reset, --no-reseed, --chat-port
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
5. **One start** ([CP-0054](/changes/cp-0054-one-start-in-docker.md)). The rest of `start` follows [CP-0053](/changes/cp-0053-one-start-for-everything.md): when `--no-chat` is not given, `docker build -f apps/chat/Dockerfile -t voiceai-chat:local apps/chat` (skipped with `--skip-build`); before the API container, when `--reset` is given or the seed stamp is missing or different (and not `--no-reseed`), a one-off `docker run --rm` of the API image with the same data mount and settings runs `uv run --no-sync voiceai seed --reset`, and the stamp is written only after it succeeds; the API container's settings gain the demo Studio passwords when none of the three is set and `--no-login` is not given. After `/healthz` answers, when `apps/chat/.env.local` has no `VOICEAI_API_KEY` a `member` key named `chat-app` is created through `http://localhost:<port>` (signing in as admin when sign-in is on) and written there. Then container `voiceai-chat` runs `docker run -d --name voiceai-chat -p <chat-port>:3100 --add-host host.docker.internal:host-gateway` with `VOICEAI_API_URL=http://host.docker.internal:<port>`, `VOICEAI_TENANT_ID`, `VOICEAI_API_KEY` and `CHAT_BRAND_NAME` in a temporary env file, and `READY` prints both URLs and, when the defaults were applied, the three accounts.
6. **status** prints whether the container runs, its port and `/healthz`; **logs** runs `docker logs` (`-f` follows, `-n` lines); **stop** removes both containers (`voiceai-local` and `voiceai-chat`). The images and the database stay; `logs --service chat` shows the chat container.

The web app is served by the API on the same origin, as on Cloud Run: there is no hot reload; run `start` again after code changes.

# Acceptance

- **DEV-15** — Given `docker_stack.py start` with defaults, when its plan is built, then it builds `voiceai:local` from `infra/Dockerfile`, runs container `voiceai-local` publishing host `8080` to the container's `8080`, mounts `apps/api/data` at `/app/apps/api/data`, passes the variables of `apps/api/.env` through a temporary env file with quotes stripped and the host-only ones (`DATABASE_URL`, `PORT`) dropped, and starts the dental mock before the API in the container; `--skip-build` has no build step, `--port 9090` publishes `9090:8080`, `--no-mock` leaves the mock out.
- **DEV-16** — Given a local API answering `/healthz` on `:8000`, when `docker_stack.py start` runs without `--force`, then it exits 1 naming the reason and starts nothing.
- **DEV-17** — Given the container running, then `http://localhost:8080/healthz` is `ok`, a Talk call to a published voice agent connects (checked by hand on the owner's laptop), and a dental tool call reaches the mock inside the container.
- **DEV-24** — Given the defaults, when the plan is built, then it also builds `voiceai-chat:local` from `apps/chat/Dockerfile` and runs container `voiceai-chat` publishing `3100:3100` with `--add-host host.docker.internal:host-gateway` and an env file; `--skip-build` skips both builds, `--chat-port 3200` publishes `3200:3100`, `--no-chat` has neither a chat build nor a chat run.
- **DEV-25** — Given no seed stamp, a stamp that differs from the hash of the seed sources, or `--reset`, then the plan has a one-off seed run (`docker run --rm`, same image, data mount and settings, `uv run --no-sync voiceai seed --reset`) before the API container and the stamp is written only after it succeeds; given a matching stamp or `--no-reseed` there is no seed run.
- **DEV-26** — Given none of the three `STUDIO_*_PASSWORD` settings set in `apps/api/.env` (empty = unset), then the API container's settings carry the three demo passwords; given one set, or `--no-login`, none is added and yours is never replaced.
- **DEV-27** — Given `apps/chat/.env.local` without a key and a ready API, then a `member` key is created through the admin login and written to it and the chat container's env file holds `VOICEAI_API_URL=http://host.docker.internal:<port>` and that key; given a key already there nothing is created; `stop` removes both containers and `status` reports both.
