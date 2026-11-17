---
type: Change Proposal
title: CP-0054 One start in Docker too - docker_stack.py starts the chat app, logins and demo data
description: python scripts/docker_stack.py start also runs the customer chat app in its own container, gives the API the local demo passwords when none is set, re-seeds the demo data when the seed changed and creates the chat key, so the owner's laptop (where dev.py cannot run) also starts everything with one command.
status: stable
cp_state: implemented
tags: [tooling, docker, chat, auth, seed]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-17T00:00:00Z" }
---

# Why

CP-0053 made `scripts/dev.py` start everything, but on the owner's laptop Windows Application Control blocks `voiceai.exe`, so the only working launcher is `scripts/docker_stack.py`, which started just the app and the mock. The owner wants the chat app, the logins and the demo data handled in the same single step there too.

# What changes

* `start` also builds and runs the customer chat app (`apps/chat`) in a second container `voiceai-chat` on host port 3100 (`--chat-port`, `--no-chat` skips it). It reaches the API at `http://host.docker.internal:<port>`.
* The same login defaults, seed stamp, `--no-login`, `--reset` and `--no-reseed` as `dev.py` ([/build/dev-launcher.md](/build/dev-launcher.md)), sharing its code. The seed runs as a one-off container on the same image, data mount and settings before the API container starts.
* After the API answers, a missing chat key is created through the admin login and kept in `apps/chat/.env.local`, then passed to the chat container as an environment variable.
* `status` reports both containers, `stop` removes both, `logs --service chat` shows the chat container.
* The first start after this change re-seeds once (no stamp yet).

# Affected specs

* [/build/docker-stack.md](/build/docker-stack.md) - the new behavior (DEV-15 reworded, DEV-24..DEV-27)

# Acceptance criteria

New: DEV-24 to DEV-27. Changed: DEV-15 (the plan also holds the chat build and run).

# Tasks

1. Spec edits (done in this CP).
2. `scripts/docker_stack.py` and `apps/chat/Dockerfile` - covers DEV-24..DEV-27.
3. Tests in `apps/api/tests/test_docker_stack.py`.

# Risks and rollout

* The chat key lives in `apps/chat/.env.local`; a `--reset` seed removes keys from the database, after which the old key is refused until `.env.local` is deleted and the stack started again.
* Demo passwords are known values; they apply only when none is set, and the containers publish on the host only.

# Out of scope

Hosting the chat app on Cloud Run, changing the API image, hot reload in Docker.
