---
type: Component Spec
title: Languages - English and Hindi with switching mid-call
description: An agent can take calls in English, Hindi or a mix of both, switching at any turn, on the realtime speech-to-speech pipeline; reply language, the safety screen, tool arguments and knowledge search each have one rule for a bilingual call.
status: stable
tags: [architecture, voice, language, runtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

Many members speak Hindi, English or both in one sentence ("mera claim status check karna hai"), and switch freely during a call. Before [CP-0037](/changes/cp-0037-hindi-english-switching.md) every part of the stack assumed English: cascade speech-to-text is fixed to `en-US`, the cascade voices are English-only Deepgram Aura-2 voices, and the safety screen matched English phrases only.

# Agent setting

`languages` in the agent config ([/data/agent-config.md](/data/agent-config.md)): a list from `en`, `hi`; it MUST contain `en`; default `["en"]`. It is part of the version snapshot.

* `["en"]` — the agent behaves exactly as before this spec: same prompt, same pipeline settings.
* `["en", "hi"]` — a **bilingual** agent: the caller may speak English, Hindi or a mix, and switch at any turn. The rest of this spec applies only to bilingual agents, except the safety screen, which applies to every agent.

There is no per-call language choice and no language menu: the caller just speaks.

# Bilingual agents run on the realtime pipeline

A bilingual agent MUST use `voice.pipeline: "realtime"` ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)). One speech-to-speech model listens to and speaks both languages and follows a switch within a turn, so no language detection, second speech-to-text model or second voice provider is needed. The cascade pipeline ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)) stays English-only.

* Saving a draft with `languages` containing `hi` and a `cascade` pipeline is allowed (the builder is mid-edit); **publishing** it fails with 422 `language_needs_realtime`.
* The tenant must allow realtime (`allowed_pipelines`, [/architecture/tenant-settings.md](/architecture/tenant-settings.md)); call admission is unchanged ([/architecture/call-admission.md](/architecture/call-admission.md)).
* Input transcription (used for the stored transcript, the safety screen and learning) is configured **without** a language, so the provider detects it per turn.
* The realtime voice (`voice.realtime.voice`, or the role default) speaks both languages; no extra setting.
* Text calls (Type tab, public text API) and evaluation runs of a bilingual agent use the text channel with the same prompt, so they are bilingual too.

# Default for new agents

A new agent is bilingual on the realtime pipeline by default, where the tenant allows it:

* `POST /api/agents` ([/api/rest-api.md](/api/rest-api.md)), and so **New agent** in the builder: when the tenant's `allowed_pipelines` contains `realtime`, the default draft config has `voice.pipeline: "realtime"` and `languages: ["en","hi"]`; otherwise it has `voice.pipeline: "cascade"` and `languages: ["en"]` (the pipeline the tenant allows, as before), so creating and saving never fails with `pipeline_not_allowed`.
* Values given in the request's `draft_config` win over these defaults.
* The default is applied once, at creation. Existing agents, seeded agents and new versions of existing agents (builder publishes, approved fixes) keep their own pipeline and languages; changing the tenant's `allowed_pipelines` later does not change any agent.
* The builder can still switch a new agent to *Cascade*; if it is bilingual, publish then asks for realtime (LANG-02) until *Hindi* is unticked.

# Language of a turn

`turn_language(text)` is deterministic: `hi` when the text contains at least one Devanagari letter (U+0900–U+097F), otherwise `en`. Hindi written in Latin letters ("mujhe madad chahiye") counts as `en` for this function; the model still understands it and replies in kind (prompt rule below).

The session keeps `caller_language`, the `turn_language` of the latest caller turn (starts at `en`). It is recorded on each `user` event as `data.language` and chooses the language of the fixed safety message. Every other fixed line (welcome, disclosure, reminders, hand-off, holding and closing lines) stays as configured in this version.

# Reply language

The system prompt of a bilingual agent carries a **Language** block ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md), variable `language_instructions`): reply in the language of the caller's latest turn, Hindi in Devanagari, switch when the caller switches; keep identifiers, amounts and dates as English words and digits. The realtime model receives it because its instructions are the system prompt plus the addendum (RV-04).

# Identifiers and tool arguments

Members mostly say member IDs, dates of birth and claim numbers in English. When they say them in Hindi, the model converts them before calling a tool (prompt rule: tool arguments are always English with ASCII digits). The runtime adds a deterministic safety net on **every string argument of every tool call**, before verification and before the business API:

1. Devanagari digits `०–९` become `0–9`.
2. Hindi month names become English month names: जनवरी January, फ़रवरी/फरवरी February, मार्च March, अप्रैल April, मई May, जून June, जुलाई July, अगस्त August, सितंबर/सितम्बर September, अक्टूबर/अक्तूबर October, नवंबर/नवम्बर November, दिसंबर/दिसम्बर December.

Read-back (realtime addendum) happens in the caller's language, with the digits as given to the tool.

# Knowledge search

Knowledge stays English and the embedder stays `BAAI/bge-small-en-v1.5` ([/architecture/knowledge.md](/architecture/knowledge.md)); no re-indexing. The model writes `search_knowledge` queries in English (prompt rule), translating the caller's question. If a query still contains a Devanagari letter, the search does not run and the tool returns `{"error": "query_not_english", "message": "Search knowledge in English: translate the caller's question and search again."}`; this error does not count toward the no-answer streak.

# Safety screen

The safety screen ([/product/healthcare-compliance.md](/product/healthcare-compliance.md), rule 6) runs on every caller turn of **every** agent with the English phrases **and** the Hindi phrases below, after Unicode NFC normalisation and lower-casing. Hindi phrases are matched on English-only agents too, because a caller in distress may switch language on any line.

* Devanagari: `आत्महत्या`, `खुदकुशी`, `ख़ुदकुशी`, `खुद को मार`, `ख़ुद को मार`, `खुद को नुकसान`, `मरना चाहता`, `मरना चाहती`, `जान दे दूं`, `जान दे दूँ`, `सीने में दर्द`, `छाती में दर्द`, `सांस नहीं`, `साँस नहीं`, `बेहोश`, `दिल का दौरा`, `हार्ट अटैक`, `बहुत खून`, `ओवरडोज़`, `ओवरडोज`, `लकवा`.
* Hindi in Latin letters: `aatmahatya`, `atmahatya`, `khudkushi`, `khud ko maar`, `khud ko nuksan`, `marna chahta`, `marna chahti`, `jaan de dun`, `seene mein dard`, `seene me dard`, `chhati mein dard`, `saans nahi`, `sans nahi`, `behosh`, `dil ka daura`.

On a match the fixed safety message is spoken in the caller's language: the English message when `caller_language` is `en`, otherwise the Hindi message of rule 6. The escalation (category `safety`) is the same. On the realtime pipeline the screen runs on the input transcript and cancels an in-flight reply as in RV-08.

# Analysis and hand-off notes

Call analysis, escalation packets and member memory are written in English whatever language the call used, so reviewers, clustering and the English embedder keep working ([/prompts/call-analysis.md](/prompts/call-analysis.md), [/prompts/escalation-packet.md](/prompts/escalation-packet.md), [/prompts/memory-extract.md](/prompts/memory-extract.md)).

# Evaluation

Test-suite scenarios get `language`: `en` (default), `hi` or `mixed` ([/architecture/test-suites.md](/architecture/test-suites.md)); the simulated caller speaks accordingly, so a bilingual agent's suite can prove switching works without a live call (realtime agents are evaluated on the text channel, RV-14).

# Acceptance

- **LANG-01** — Given an agent config with `languages` `["en","hi"]`, `["en"]` or absent, when saved, then it is accepted, absent means `["en"]`, and the value is in the published snapshot; `["hi"]`, `["en","fr"]` or `[]` returns 422.
- **LANG-02** — Given a draft with `languages` `["en","hi"]` and pipeline `cascade`, when saved, then it is accepted; when published, then 422 `language_needs_realtime` and no version is created; with pipeline `realtime` it publishes.
- **LANG-03** — Given an English-only agent, then its rendered system prompt has no Language block and is otherwise the same as before this spec (blank lines aside), and its realtime `session.update` and cascade pipeline settings are unchanged.
- **LANG-04** — Given a bilingual agent, then its system prompt (text channel and realtime instructions) contains the Language block; given an English-only agent, it does not.
- **LANG-05** — Given `turn_language`, then "मेरा claim status बताइए" is `hi`, "mera claim status batao" and "What is my deductible?" are `en`; each stored `user` event of a bilingual call carries `data.language`.
- **LANG-06** — Given a tool call whose arguments are `{"member_id": "EVG-४८२९१३", "date_of_birth": "<seeded date of birth in YYYY-MM-DD, written with Devanagari digits>"}`, when executed, then the business API receives the ASCII member ID and date and verification succeeds for that seeded member; and the normaliser turns `"१४ मार्च १९८६"` into `"14 March 1986"`.
- **LANG-07** — Given a `search_knowledge` call with a Devanagari query, then no search runs, the tool result is `query_not_english`, and the no-answer streak does not increase; an English query searches as before (KN-04).
- **LANG-08** — Given any agent (English-only or bilingual), when a caller turn contains "मुझे सीने में दर्द हो रहा है" or "mujhe seene mein dard hai", then no LLM request is made, a `safety` escalation is created, and the spoken message is the Hindi safety message for the Devanagari turn and the English safety message for the Latin-letter turn; on the realtime pipeline the in-flight reply is cancelled and the message spoken verbatim as in RV-08.
- **LANG-09** — Given a bilingual realtime agent, when the session is configured, then the input transcription carries no `language`.
- **LANG-10** — Given a test-suite scenario with `language: mixed` run against a bilingual agent on the scripted fake LLM, then the simulator prompt carries the mixed-language line, the run completes, and the call's `user` events include both `en` and `hi` turns.
- **LANG-11** — Given a tenant whose `allowed_pipelines` is `["cascade","realtime"]`, when `POST /api/agents` is sent with only a name and description, then the new draft has `voice.pipeline: "realtime"` and `languages: ["en","hi"]`, and it saves and publishes; given a tenant with `["cascade"]`, the new draft has `cascade` and `["en"]` and saves without `pipeline_not_allowed`; given a request whose `draft_config` sets `voice.pipeline: "cascade"` and `languages: ["en"]`, those values are kept; existing agents of both tenants are unchanged.
