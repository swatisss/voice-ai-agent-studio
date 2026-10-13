# Architecture

* [System overview](system-overview.md) - Components, deployment shape and the three core flows
* [Modular structure](modular-structure.md) - Layers, the nine modules, the ports and contracts between them, and the CI rules that hold the boundaries
* [Tech stack](tech-stack.md) - Languages, frameworks, providers and version policy
* [Agent runtime](agent-runtime.md) - The shared brain: turn loop, state, built-in tools, guards
* [Voice pipeline](voice-pipeline.md) - Browser audio over WebSocket through Pipecat: VAD, STT, turn detection, TTS, interruptions
* [LLM gateway](llm-gateway.md) - Roles mapped to provider models over a pluggable wire adapter, fallback, JSON mode, cost accounting
* [Knowledge](knowledge.md) - Ingestion (text, file, URL, OKF), chunking, embeddings, search with no-answer threshold
* [Tools and skills](tools-and-skills.md) - HTTP tool definitions, execution, verification gate, skill format
* [Turn detection](turn-detection.md) - Normal and semantic end-of-turn detection, settings, evaluators, interruptions, live controls
* [Personas](personas.md) - Tenant persona library, snapshot resolution, per-call overrides and live switching
* [Call modes](call-modes.md) - Inbound, outbound and internal modes, call context, outbound targets and opening
* [Call ending and feedback](call-ending-and-feedback.md) - How calls close (goodbye, farewell, hand-off, silence, max length) and the thumbs up/down feedback that feeds Insights
* [Visual evidence intake](visual-intake.md) - Frames captured on demand, an observation with a confidence it may withhold, pinned evidence, the case and its routing
* [Talking avatar](avatar.md) - How the agent appears as a live face in a video call: pipeline position, degradation, lifetime, and why its frames are never evidence
* [Media storage](media-storage.md) - The blob-store port, bounded frames, the retention window and authorised access only
* [Reference and sample imagery](imagery.md) - The seeded synthetic images offered when there is no camera, and why nothing is generated at runtime
* [Escalation](escalation.md) - Triggers, categories, groundwork packet, human console lifecycle
* [Fleet learning](fleet-learning.md) - Call analysis, gap clustering, impact, fix drafting, approval
* [Evaluation](evaluation.md) - Simulated callers, judge, baseline vs candidate, regression scenarios
* [Jobs and events](jobs-and-events.md) - Background job queue and server-sent event bus
* [Multi-tenancy](multi-tenancy.md) - Tenant resolution and isolation rules
* [Deployment](deployment.md) - Local dev and GCP Cloud Run topology
