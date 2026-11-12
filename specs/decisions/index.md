# Decisions

* [ADR-0001 Spec-driven development with OKF](adr-0001-spec-driven-okf.md) - Specs in an OKF bundle are the source of truth and ship with code
* [ADR-0002 Voice pipeline](adr-0002-voice-pipeline.md) - Pipecat over a plain WebSocket with our own turn aggregation and brain processor
* [ADR-0003 LLM gateway](adr-0003-llm-gateway.md) - One OpenAI-compatible client for Groq and OpenRouter, roles in YAML
* [ADR-0004 Storage and vectors](adr-0004-storage-and-vectors.md) - SQLite locally, Postgres in the cloud, in-process NumPy vector search, local embeddings
* [ADR-0005 Single service](adr-0005-single-service.md) - API, voice, jobs, events and static web in one process and one Cloud Run service
* [ADR-0006 Turn detection on Pipecat](adr-0006-turn-detection.md) - Own normal/semantic turn detection instead of adopting LiveKit's turn detector
* [ADR-0007 OpenAI as a third LLM provider](adr-0007-openai-provider.md) - OpenAI beside Groq and OpenRouter; Groq stays primary, OpenAI is every role's last fallback and a one-line switch
* [ADR-0008 Telephony and realtime voice](adr-0008-telephony-and-realtime-voice.md) - Twilio Media Streams for inbound phone calls on Cloud Run; OpenAI Realtime speech-to-speech as an optional per-agent pipeline
* [ADR-0009 Agent memory](adr-0009-agent-memory.md) - Our own mem0-style memory maintenance after each call that retires instead of deleting; research on mem0, Zep, Memory Bank and SaaS builders
* [ADR-0010 Caller verification](adr-0010-caller-verification.md) - A registered number identifies, the date of birth verifies; research on health-plan practice, caller-ID spoofing and Twilio testing
* [ADR-0011 Evaluation and self-learning](adr-0011-evaluation-and-self-learning.md) - One scorer for online scoring, test suites and nightly self-learning; checks derived from the declarative config; only humans publish; research on voice-agent evaluation
* [ADR-0012 Public API and supervisor routing](adr-0012-public-api-and-supervisor-routing.md) - Key-authenticated /v1 API per tenant, supervisor routing from an auto-synced capability catalog (embeddings, then Jev, Laya or an LLM), agent transfer, webhooks; research on voice-session APIs and routing models
* [ADR-0013 Carrier adapters and the paths to SIP](adr-0013-carrier-adapters-and-sip-paths.md) - One carrier-adapter interface, Twilio first; SIP through a carrier trunk, the customer's Asterisk over WebSocket or a speech model's SIP endpoint; research on Dograh and Asterisk
* [ADR-0014 Contact providers](adr-0014-contact-providers.md) - Brevo for email, Twilio for SMS and message calls, an outbox when nothing is configured; message calls instead of AI callbacks; research on free email and SMS plans
