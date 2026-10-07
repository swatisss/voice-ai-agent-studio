# Decisions

* [ADR-0001 Spec-driven development with OKF](adr-0001-spec-driven-okf.md) - Specs in an OKF bundle are the source of truth and ship with code
* [ADR-0002 Voice pipeline](adr-0002-voice-pipeline.md) - Pipecat over a plain WebSocket with our own turn aggregation and brain processor
* [ADR-0003 LLM gateway](adr-0003-llm-gateway.md) - One OpenAI-compatible client for Groq and OpenRouter, roles in YAML
* [ADR-0004 Storage and vectors](adr-0004-storage-and-vectors.md) - SQLite locally, Postgres in the cloud, in-process NumPy vector search, local embeddings
* [ADR-0005 Single service](adr-0005-single-service.md) - API, voice, jobs, events and static web in one process and one Cloud Run service
* [ADR-0006 Turn detection on Pipecat](adr-0006-turn-detection.md) - Own normal/semantic turn detection instead of adopting LiveKit's turn detector
