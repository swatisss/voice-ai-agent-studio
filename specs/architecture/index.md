# Architecture

* [System overview](system-overview.md) - Components, deployment shape and the three core flows
* [Tech stack](tech-stack.md) - Languages, frameworks, providers and version policy
* [Agent runtime](agent-runtime.md) - The shared brain: turn loop, state, built-in tools, guards
* [Voice pipeline](voice-pipeline.md) - Browser audio over WebSocket through Pipecat: VAD, STT, turn detection, TTS, interruptions
* [LLM gateway](llm-gateway.md) - Roles mapped to Groq/OpenRouter models, fallback, JSON mode, cost accounting
* [Knowledge](knowledge.md) - Ingestion (text, file, URL, OKF), chunking, embeddings, search with no-answer threshold
* [Tools and skills](tools-and-skills.md) - HTTP tool definitions, execution, verification gate, skill format
* [Escalation](escalation.md) - Triggers, categories, groundwork packet, human console lifecycle
* [Fleet learning](fleet-learning.md) - Call analysis, gap clustering, impact, fix drafting, approval
* [Evaluation](evaluation.md) - Simulated callers, judge, baseline vs candidate, regression scenarios
* [Jobs and events](jobs-and-events.md) - Background job queue and server-sent event bus
* [Multi-tenancy](multi-tenancy.md) - Tenant resolution and isolation rules
* [Deployment](deployment.md) - Local dev and GCP Cloud Run topology
