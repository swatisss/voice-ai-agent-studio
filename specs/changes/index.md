# Change proposals

* [CP-0001 Initial platform build](cp-0001-initial-platform.md) - Build the v1 platform: builder, voice and text test calls, escalation with groundwork packets, fleet learning with eval-gated fixes
* [CP-0002 Spec enforcement in CI and contributor onboarding](cp-0002-spec-enforcement-and-onboarding.md) - CI gate, PR-level spec-first/log/lifecycle rules, acceptance ratchet, setup script, README
* [CP-0008 OpenAI as a third LLM provider](cp-0008-openai-provider.md) - OpenAI key from .env, two OpenAI models, last fallback of every role, one-line role switch, health dot
* [CP-0006 Customer Support & Channels use cases](cp-0006-customer-support-use-cases.md) - Seven insurer use cases, outbound and internal call modes, synthetic insurance API and knowledge, use-case gallery
* [CP-0007 Turn-detection modes and a persona library](cp-0007-turn-detection-and-personas.md) - Normal/semantic turn detection and personas, configurable per agent, per call and live from the UI
* [CP-0005 Health-insurer portal look and feel](cp-0005-insurer-portal-theme.md) - Blue brand palette, top navigation, pill buttons, WCAG AA contrast (checked by a test)
* [CP-0004 One-command dev launcher](cp-0004-one-command-dev-launcher.md) - scripts/dev.py starts web + API together with prefixed logs and clean shutdown
* [CP-0003 Honor LLM role overrides from apps/api/.env](cp-0003-env-file-role-overrides.md) - LLM_ROLE_<ROLE> now works from the .env file, not only real environment variables
