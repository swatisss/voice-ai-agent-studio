# Architecture

* [System overview](system-overview.md) - Components, deployment shape and the three core flows
* [Tech stack](tech-stack.md) - Languages, frameworks, providers and version policy
* [Agent runtime](agent-runtime.md) - The shared brain: turn loop, state, built-in tools, guards
* [Voice pipeline](voice-pipeline.md) - Browser audio over WebSocket through Pipecat: VAD, STT, turn detection, TTS, interruptions
* [LLM gateway](llm-gateway.md) - Roles mapped to Groq, OpenRouter or OpenAI models, fallback, JSON mode, cost accounting
* [Knowledge](knowledge.md) - Ingestion (text, file, URL, OKF), chunking, embeddings, search with no-answer threshold
* [Tools and skills](tools-and-skills.md) - HTTP tool definitions, execution, verification gate, skill format
* [Turn detection](turn-detection.md) - Normal and semantic end-of-turn detection, settings, evaluators, interruptions, live controls
* [Personas](personas.md) - Tenant persona library, snapshot resolution, per-call overrides and live switching
* [Call modes](call-modes.md) - Inbound, outbound and internal modes, call context, outbound targets and opening
* [Call ending and feedback](call-ending-and-feedback.md) - How calls close (goodbye, farewell, hand-off, silence, max length) and the thumbs up/down feedback that feeds Insights
* [Telephony](telephony.md) - Inbound phone calls through Twilio Media Streams: number mapping, webhook and stream, IVR context, transfer, security
* [Realtime voice](realtime-voice.md) - The optional OpenAI speech-to-speech pipeline per agent: streaming, latency, shared runtime, trade-offs
* [Languages](languages.md) - English and Hindi with switching mid-call on realtime agents; Hindi safety phrases, English tool arguments and knowledge queries
* [Contact tools](contact-tools.md) - Email (Brevo), SMS and message calls (Twilio) on every agent: registered contact after verification or a confirmed address, masked records, outbox, no delivery from simulations
* [Escalation](escalation.md) - Triggers, categories, groundwork packet, human console lifecycle
* [Fleet learning](fleet-learning.md) - Call analysis, gap clustering, impact, fix drafting, approval
* [Evaluation](evaluation.md) - Simulated callers, judge, baseline vs candidate, regression scenarios
* [Self-learning](self-learning.md) - The nightly run that turns each agent's calls into typed config proposals, proves them offline and leaves them for a human; signals, gate, inbox, guardrails
* [Learning actions](learning-actions.md) - Findings of evaluation and learning as ranked actions with one next step each (fix did not hold, answer needed, check failing, drift, scenario failing), closing themselves when cleared; fix verification
* [How self-learning should work](self-learning-target.md) - Review of the learning loop as built (verified end to end 2026-11-01), its gaps (roadmap R14-R20) and the target loop; draft, nothing built from it yet
* [Test suites](test-suites.md) - Offline evaluation: per-agent scenarios with expectations run k times by a simulated caller against the published version, the draft or an earlier version, scored and reported as pass rate and pass^k
* [Call scoring](call-scoring.md) - Online evaluation: a scorecard per real call with checks derived from the version config, rollups per version, drift, reviews and judge calibration
* [Jobs and events](jobs-and-events.md) - Background job queue and server-sent event bus
* [Multi-tenancy](multi-tenancy.md) - Tenant resolution and isolation rules
* [Call admission](call-admission.md) - One decision for every way a voice call starts: pipeline allowed, credential available, the call plan
* [Agent memory](agent-memory.md) - What an agent remembers about a verified member across calls, maintained by the agent itself after each call; expiry, erasure and what the Studio shows
* [Caller verification](caller-verification.md) - Registered number identifies, date of birth verifies; member ID and date of birth otherwise; attempts, attestation and playground testing
* [Tenant settings and credentials](tenant-settings.md) - Per-tenant voice pipeline allowlist and own OpenAI key for realtime calls
* [Supervisor routing](supervisor-routing.md) - Front desk and supervisor: the embedding by default or a configured decision model with embedding fallback, PHI mode, clarification, default agents, front-desk phone numbers, routing trace
* [Capability catalog](capability-catalog.md) - Per-agent capability profiles built and re-indexed automatically from description, use cases, tools and knowledge; editable use cases; the routing suite
* [Agent transfer](agent-transfer.md) - The transfer_to_agent tool: segments, what carries over, transfer limit, misroute checks and learning
* [Webhooks](webhooks.md) - Signed, retried webhooks for public-API conversations; IDs only by default
* [WebRTC transport](webrtc-transport.md) - WebRTC voice for public-API and playground conversations, TURN on Cloud Run
* [Deployment](deployment.md) - Local dev and GCP Cloud Run topology
* [Studio sign-in and roles](studio-auth.md) - Two demo accounts, signed session cookie, the API guard and admin-only table, who is recorded
