# Change proposals

* [CP-0001 Initial platform build](cp-0001-initial-platform.md) - Build the v1 platform: builder, voice and text test calls, escalation with groundwork packets, fleet learning with eval-gated fixes
* [CP-0002 Spec enforcement in CI and contributor onboarding](cp-0002-spec-enforcement-and-onboarding.md) - CI gate, PR-level spec-first/log/lifecycle rules, acceptance ratchet, setup script, README
* [CP-0018 The text loop drives the turn policy](cp-0018-text-loop-drives-turn-policy.md) - respond() drives the same turn-policy events as the realtime bridge; text calls store the same event data as realtime calls
* [CP-0017 Effective call settings](cp-0017-effective-call-settings.md) - One resolution of persona, turn detection and pipeline for a call; live changes go through the session and the pipeline subscribes
* [CP-0016 Turn policy inside AgentSession](cp-0016-turn-policy-in-agent-session.md) - Events in, decisions out: the cascade loop and the realtime bridge stop re-implementing turn rules and their order
* [CP-0015 Call admission](cp-0015-call-admission.md) - One decision for every way a voice call starts; voice calls with no usable key are refused up front
* [CP-0014 Tenant pipeline allowlist and per-tenant OpenAI key](cp-0014-tenant-pipeline-allowlist-and-openai-key.md) - Realtime is opt-in per tenant (save, publish, call start); a tenant's own encrypted OpenAI key serves its realtime calls, with optional platform fallback; Settings page
* [CP-0013 One-command phone demo](cp-0013-one-command-phone-demo.md) - scripts/phone_demo.py: fill in .env, run one script, call the number
* [CP-0012 Phone channel (Twilio) and optional realtime speech-to-speech voice](cp-0012-phone-channel-and-realtime-voice.md) - Inbound Twilio calls to published agents, OpenAI Realtime as a per-agent pipeline, new Insurance Claims Agent, local phone runbook
* [CP-0011 Calls close properly and callers rate them](cp-0011-call-ending-and-feedback.md) - Hand-off, farewell, silence and max length end calls; thumbs up/down after a call feeds Insights
* [CP-0010 Simpler Test call page and a spoken welcome in voice calls](cp-0010-simpler-test-call-and-voice-welcome.md) - No use-case cards, Talk | Type in the call card, technical details behind a switch, the agent speaks first in Talk mode
* [CP-0009 Simplified UI - left navigation, focused dashboard, Echo Mind branding](cp-0009-simplified-ui-sidebar-and-branding.md) - Left sidebar replaces the top header, four-tile dashboard (calls, containment, escalated to human, response time), product named Echo Mind Voice Agent Studio
* [CP-0008 OpenAI as a third LLM provider](cp-0008-openai-provider.md) - OpenAI key from .env, two OpenAI models, last fallback of every role, one-line role switch, health dot
* [CP-0006 Customer Support & Channels use cases](cp-0006-customer-support-use-cases.md) - Seven insurer use cases, outbound and internal call modes, synthetic insurance API and knowledge, use-case gallery
* [CP-0007 Turn-detection modes and a persona library](cp-0007-turn-detection-and-personas.md) - Normal/semantic turn detection and personas, configurable per agent, per call and live from the UI
* [CP-0005 Health-insurer portal look and feel](cp-0005-insurer-portal-theme.md) - Blue brand palette, top navigation, pill buttons, WCAG AA contrast (checked by a test)
* [CP-0004 One-command dev launcher](cp-0004-one-command-dev-launcher.md) - scripts/dev.py starts web + API together with prefixed logs and clean shutdown
* [CP-0003 Honor LLM role overrides from apps/api/.env](cp-0003-env-file-role-overrides.md) - LLM_ROLE_<ROLE> now works from the .env file, not only real environment variables
