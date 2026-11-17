---
type: Change Proposal
title: CP-0053 One start for everything - dev.py sets up logins, chat and demo data
description: python scripts/dev.py alone starts the web app, API, dental mock and the customer chat app, signs the three demo accounts in with local-only default passwords, and re-seeds the demo data when the seed changed, so the owner only sets vendor keys in .env.
status: stable
cp_state: implemented
tags: [tooling, dev, auth, chat, seed]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-17T00:00:00Z" }
---

# Why

Trying the platform end to end took four separate steps: set three Studio passwords, start the stack, start the chat app with `--chat`, and run `voiceai seed --reset` after pulling changes. The owner wants to put only vendor details (OpenAI, Deepgram, Twilio, LiveKit) in `apps/api/.env`, run one command and have everything ready.

# What changes

* **Chat by default.** `python scripts/dev.py` also starts the chat app on :3100 (`--no-chat` skips it; `--chat` is kept and does nothing new). If `apps/chat/node_modules` is missing the launcher installs it first.
* **Demo logins by default.** When none of `STUDIO_ADMIN_PASSWORD`, `STUDIO_REVIEWER_PASSWORD` and `STUDIO_SPECIALIST_PASSWORD` is set (an empty value counts as unset) in the environment or `apps/api/.env`, the launcher gives the API process local demo passwords (`admin-demo-pass`, `reviewer-demo-pass`, `specialist-demo-pass`) and prints the three accounts. A password you set yourself is never overridden, and `--no-login` keeps sign-in off. The defaults exist only in the launcher: the API itself, Docker and Cloud Run are unchanged, and `voiceai serve` binds 127.0.0.1.
* **Chat key through the login.** The launcher creates the chat app's API key by signing in as admin first, so it works with sign-in on.
* **Demo data follows the seed.** A stamp (a hash of the seed code and the demo-data specs, one per database) records which seed the database holds. When it is missing or differs, the launcher runs `voiceai seed --reset` once before starting and writes the stamp after it succeeds; normal restarts keep your data. `--reset` forces a re-seed, `--no-reseed` skips it.

# Affected specs

* [/build/dev-launcher.md](/build/dev-launcher.md) - the new defaults and flags (DEV-18 reworded, DEV-19..DEV-23)

# Acceptance criteria

New: DEV-19 to DEV-23. Changed: DEV-18 (the chat service is on by default).

# Tasks

1. Spec edits (done in this CP).
2. `scripts/dev.py`: chat on by default and auto-install, login defaults, seed stamp and step, key provisioning through the login, banner - covers DEV-18..DEV-23.
3. `scripts/setup.py --install` also installs the chat app; `apps/api/.env.example` comment.
4. Tests in `apps/api/tests/test_dev_launcher.py`.

# Risks and rollout

* The first start after this change re-seeds once (no stamp yet), which resets any demo data you changed. After that only a changed seed triggers it.
* Known default passwords are acceptable only because the launcher is local and the API listens on 127.0.0.1; deployments keep setting their own.

# Out of scope

Changing the API's sign-in rules, the Docker stack launcher, Cloud Run, and seeding anything but the demo tenant data.
