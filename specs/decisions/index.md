# Decisions

* [ADR-0001 Spec-driven development with OKF](adr-0001-spec-driven-okf.md) - Specs in an OKF bundle are the source of truth and ship with code
* [ADR-0002 Voice pipeline](adr-0002-voice-pipeline.md) - Pipecat over a plain WebSocket with our own turn aggregation and brain processor (amended by ADR-0009 for video)
* [ADR-0003 LLM gateway](adr-0003-llm-gateway.md) - One OpenAI-compatible client for Groq and OpenRouter, roles in YAML
* [ADR-0004 Storage and vectors](adr-0004-storage-and-vectors.md) - SQLite locally, Postgres in the cloud, in-process NumPy vector search, local embeddings
* [ADR-0005 Single service](adr-0005-single-service.md) - API, voice, jobs, events and static web in one process and one Cloud Run service
* [ADR-0006 Turn detection on Pipecat](adr-0006-turn-detection.md) - Own normal/semantic turn detection instead of adopting LiveKit's turn detector
* [ADR-0007 OpenAI as a third LLM provider](adr-0007-openai-provider.md) - OpenAI beside Groq and OpenRouter; Groq stays primary, OpenAI is every role's last fallback and a one-line switch
* [ADR-0008 Modular monolith with ports and adapters](adr-0008-modular-monolith.md) - One deployable still, layered into ports, adapters, core, eight modules and a composition root, enforced in CI
* [ADR-0009 LiveKit Cloud for the video channel](adr-0009-video-channel.md) - Video calls run on a LiveKit Cloud room with Pipecat's LiveKit transport; voice calls keep the plain WebSocket
* [ADR-0010 Store captured frames, with a clock on every object](adr-0010-media-retention.md) - The first byte storage in the product, kept narrow: one port, bounded frames, a retention window, and observation text that outlives the image
