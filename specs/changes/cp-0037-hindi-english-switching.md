---
type: Change Proposal
title: CP-0037 Hindi and English, switching mid-call
description: A bilingual agent setting lets callers speak English, Hindi or a mix and switch at any turn on the realtime speech-to-speech pipeline - reply in the caller's language, Hindi safety screen, identifiers and knowledge queries normalised to English.
status: stable
cp_state: implemented
tags: [voice, language, runtime, safety]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

The owner's callers speak Hindi, English or both, and switch in the middle of a call. Today the stack does not understand Hindi:

* Cascade speech-to-text is fixed to `en-US` (`voice/pipeline.py`, [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) step 2), so Hindi speech is transcribed as nonsense English before the model sees it.
* Every cascade voice is a Deepgram Aura-2 voice. Aura-2 speaks English, Spanish, Dutch, French, German, Italian and Japanese; there is no Hindi voice (Deepgram TTS docs and changelog, checked 2026-11-12).
* The realtime pipeline sets no transcription language and its model can understand and speak Hindi, but nothing tells it to reply in the caller's language.
* The safety screen matches English phrases only: a caller saying "सीने में दर्द" (chest pain) or "आत्महत्या" (suicide) would not get the safety message or a nurse. This is the most serious gap.
* [/product/scope.md](/product/scope.md) lists "Languages other than English" as out of scope.

**Decision (owner, 2026-11-12):** bilingual agents run on the OpenAI realtime speech-to-speech pipeline only. One model hears and speaks both languages and follows a switch within a sentence, so no second speech-to-text setting, language detection step or second voice provider is needed. The alternatives considered were Hindi on both pipelines (Deepgram `nova-3` `language=multi` plus a new ElevenLabs voice) and switching from cascade to realtime mid-call on the first Hindi turn; both were rejected as more to build and run for the same caller experience.

# What changes

* An agent has `languages`: `["en"]` (default, unchanged behavior) or `["en","hi"]` (bilingual). Full rules: [/architecture/languages.md](/architecture/languages.md).
* A bilingual agent must use the realtime pipeline: publishing a bilingual cascade agent fails with 422 `language_needs_realtime`. The cascade pipeline stays English-only and unchanged.
* For bilingual realtime calls the input transcription has no forced language.
* The bilingual agent's system prompt gets a Language block: reply in the language of the caller's latest turn, switch when they switch, Hindi in Devanagari, identifiers and amounts in English and digits, tool arguments and knowledge queries always in English. Text calls of the same agent are bilingual too.
* Identifiers spoken in Hindi: the model converts them; the runtime also converts Devanagari digits and Hindi month names in every tool argument before verification and the business API.
* Knowledge stays English with the same English embedder. A Devanagari search query is bounced back to the model to search again in English.
* Safety screen: Hindi phrases (Devanagari and Latin letters) on **every** agent; the safety message is spoken in Hindi when the triggering turn is in Devanagari.
* Call analysis, escalation packets and memory are always written in English.
* Test-suite scenarios get `language` (`en`, `hi`, `mixed`) so switching is tested offline.
* The agent builder gets a Languages control that requires the Realtime pipeline for Hindi.
* **New agents default to bilingual realtime** (owner's request, 2026-11-12): on a tenant that allows realtime, a new agent starts with `voice.pipeline: "realtime"` and `languages: ["en","hi"]`; on a cascade-only tenant it starts as today (cascade, English), so creation never fails. Existing and seeded agents are unchanged.

Example, bilingual agent:

> Caller: "Hi, mujhe apne claim ka status jaanna hai."
> Agent: "ज़रूर, मैं मदद करती हूँ। कृपया अपना member ID बताइए।"
> Caller: "EVG four eight two nine one three."
> Agent: "धन्यवाद। आपकी जन्मतिथि क्या है?"
> Caller: "Fourteen March, nineteen eighty-six. Actually, can we continue in English?"
> Agent: "Of course. Your claim from September 28th is approved..."

# Affected specs

* [/architecture/languages.md](/architecture/languages.md) - **new**: the setting, realtime-only rule, turn language, reply language, identifier normalisation, knowledge query rule, Hindi safety phrases, evaluation, the default for new agents; LANG-01..LANG-11
* [/product/scope.md](/product/scope.md) - Hindi (realtime agents) moves into scope; other languages stay out
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rule 6: Hindi safety phrases and the Hindi safety message
* [/product/compliance-evidence.md](/product/compliance-evidence.md) - C5 cites LANG-08
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - cascade stays English-only
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md) - bilingual agents: transcription language and reply language
* [/architecture/knowledge.md](/architecture/knowledge.md) - English-only queries
* [/architecture/test-suites.md](/architecture/test-suites.md) - scenario `language`
* [/data/agent-config.md](/data/agent-config.md) - `languages` and its default for new agents
* [/api/rest-api.md](/api/rest-api.md) - `POST /api/agents` default config depends on the tenant's pipelines
* [/data/data-model.md](/data/data-model.md) - `eval_scenarios.language`
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - `language_instructions` variable and Language block
* [/prompts/caller-simulator.md](/prompts/caller-simulator.md) - language line in `caller_style`
* [/prompts/call-analysis.md](/prompts/call-analysis.md), [/prompts/escalation-packet.md](/prompts/escalation-packet.md), [/prompts/memory-extract.md](/prompts/memory-extract.md) - write in English
* [/ui/agent-builder.md](/ui/agent-builder.md) - Languages control; New agent starts bilingual realtime where allowed

# Acceptance criteria

New, in [/architecture/languages.md](/architecture/languages.md): **LANG-01** to **LANG-11**. New UI criterion **UI-73** in [/ui/agent-builder.md](/ui/agent-builder.md). Existing criteria unchanged; VO-06, RV-04, RV-08, KN-04 and TEST-07 keep passing for English-only agents.

# Tasks

1. Spec edits (this CP).
2. Config: `languages` validation and snapshot; publish check `language_needs_realtime`; tenant-dependent default config in `POST /api/agents` — covers LANG-01, LANG-02, LANG-11.
3. Runtime: `language_instructions` prompt variable; `turn_language`, `caller_language`, `data.language` on user events; tool-argument normaliser; `query_not_english` — covers LANG-03..LANG-07.
4. Safety: Hindi phrases and the Hindi message in the safety screen, text channel and realtime bridge — covers LANG-08; add LANG-08 to the compliance evidence row C5.
5. Realtime: no transcription language for bilingual agents — covers LANG-09.
6. Prompts and evaluation: English-output line in analysis, packet and memory prompts; simulator language line; test-suite scenario `language`; a scripted Hindi caller in the fake LLM — covers LANG-10.
7. Web: Languages control in the builder — covers UI-73.
8. Manual check (paid, ask the owner first): one live realtime call switching Hindi → English → Hindi, noted in [/verification/spikes.md](/verification/spikes.md).

# Risks and rollout

* **Safety wording and numbers.** The Hindi safety message translates the fixed English message and keeps 911 and 988 (US). If Hindi callers are in India the numbers are wrong (112, Tele-MANAS 14416). A clinical or compliance reviewer must approve the Hindi text before any real caller hears it.
* **Phrase lists miss things.** Keyword safety screening in two scripts and romanised Hindi is weaker than in English; spellings vary. A follow-up could add a small classifier; the deterministic list stays as the floor.
* **Safety on realtime is after the fact.** As today (RV-08), the realtime model may start replying before the transcript arrives; the screen then cancels the reply and speaks the fixed message.
* **Cost.** Bilingual agents are realtime agents, which cost more per minute than the cascade ([/architecture/realtime-voice.md](/architecture/realtime-voice.md) Cost), and the tenant must allow realtime.
* **Latin-letter Hindi** ("mujhe madad chahiye") is understood by the model but counts as English for the safety message language; the escalation itself still happens.
* **New-agent default costs more.** Every new agent on a realtime-enabled tenant (today `evergreen-care`) is a realtime agent: higher cost per minute, and its voice calls need an OpenAI key (tenant key or platform fallback) instead of the Deepgram key. The sandbox tenant (cascade only) and the demo walkthrough, which builds its agent there, are unaffected.
* **Rollout:** absent `languages` means `["en"]` and the new default applies only at creation, so no existing agent changes. No seeded agent becomes bilingual unless the owner asks (open question; the Insurance Claims Agent is the natural candidate because it already runs on realtime). No data migration.

# Out of scope

* Hindi on the cascade pipeline (Deepgram multilingual speech-to-text and a Hindi-capable voice provider); switching pipeline mid-call.
* Languages other than English and Hindi; a language menu or IVR language choice.
* Hindi versions of the welcome, disclosure, silence reminder, hand-off, holding and closing lines (they stay as configured).
* Hindi farewell phrases for the deterministic farewell rule (CE-02); the model's `end_call` still ends Hindi goodbyes.
* Hindi or multilingual knowledge articles and a multilingual embedder.
* Hindi in the Studio UI.
