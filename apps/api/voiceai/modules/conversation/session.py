"""AgentSession - the shared brain for voice, text and simulation channels.

Spec: /architecture/agent-runtime.md, /architecture/escalation.md (Triggers)
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import jobs
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.errors import ApiError
from voiceai.core.events import bus
from voiceai.modules.knowledge.contract import search_knowledge as kb_search
from voiceai.core.llm.gateway import LLMError, gateway
from voiceai.core.toolcalling import ToolCaller, tool_caller
from voiceai.modules.agentcfg.contract import effective_turn, persona_dict, settings_view
from voiceai.core.tables import Agent, AgentVersion, Call, CallEvent, Persona, Tenant
from voiceai.core.handoff import handoff_desk
from voiceai.core.postcall import post_call_analysis
from voiceai.modules.conversation import endings, outbound, safety
from voiceai.modules.conversation.prompt import system_prompt
from voiceai.modules.conversation.state import CallState
from voiceai.modules.conversation.tools import ToolExecutor, all_schemas, truncate

log = logging.getLogger("voiceai.runtime")

MAX_TOOL_ROUNDS = 4
HISTORY_LIMIT = 30
FILLER = "One moment while I check that."
APOLOGY_OUTAGE = "I'm sorry, I'm having trouble right now. Let me connect you with someone who can help."
APOLOGY_TOOLS = "I'm sorry, I wasn't able to finish looking that up."
GOODBYE = endings.GOODBYE

REGISTRY: dict[str, AgentSession] = {}


def _trim_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last N messages, starting at a user message so tool messages keep their parent."""
    if len(history) <= HISTORY_LIMIT:
        return history
    tail = history[-HISTORY_LIMIT:]
    for i, m in enumerate(tail):
        if m["role"] == "user":
            return tail[i:]
    return tail


async def create_call(
    s: AsyncSession, tenant_id: str, agent_id: str, channel: str, is_eval: bool = False, live: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None, caller: ToolCaller | None = None,
) -> Call:
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if not agent:
        raise ApiError(404, "agent_not_found", "Agent not found")
    if not agent.published_version_id:  # API-01
        raise ApiError(409, "agent_not_published", "Publish the agent before starting a call")
    version = await s.get(AgentVersion, agent.published_version_id)
    config = version.config if version else {}
    mode = config.get("mode", "inbound")
    meta: dict[str, Any] = {"live": live} if live else {}
    if mode == "outbound" and not is_eval:  # OB-01: the callee must be one of the agent's targets
        ref = str((context or {}).get("member_ref") or "")
        targets = await outbound.fetch_targets((config.get("outbound") or {}).get("targets_url", ""), caller or tool_caller())
        target = next((t for t in targets if t["member_ref"] == ref), None)
        if target is None:
            raise ApiError(422, "unknown_target", "Choose a person from the outbound target list")
        meta["context"] = outbound.build_context(target)
    call = Call(
        tenant_id=tenant_id, agent_id=agent.id, agent_version_id=agent.published_version_id, channel=channel,
        direction=mode, is_eval=is_eval, meta=meta,
    )
    s.add(call)
    await s.flush()
    return call


class AgentSession:
    def __init__(
        self, *, call: Call, config: dict[str, Any], tenant_name: str, caller: ToolCaller | None = None,
        history: list[dict[str, Any]] | None = None, state: CallState | None = None, seq: int = 0,
        live: dict[str, Any] | None = None, context: dict[str, Any] | None = None,
    ) -> None:
        self.call_id = call.id
        self.context: dict[str, Any] = dict(context or {})  # outbound call context (OB-01)
        self.tenant_id = call.tenant_id
        self.agent_id = call.agent_id
        self.channel = call.channel
        self.is_eval = call.is_eval
        self.started_at = call.started_at or utcnow()
        self.config = config
        self.base_persona: dict[str, Any] = dict(config.get("persona") or {})  # the version's persona, for "reset to default"
        self.live: dict[str, Any] = dict(live or {})  # persisted overrides: persona_id, turn_detection
        self.tenant_name = tenant_name
        self.history: list[dict[str, Any]] = history or []
        self.state = state or CallState()
        self.end_reason: str | None = None  # why this session ended (CE-06: the voice pipeline reports it to the browser)
        self.seq = seq
        self.tools = ToolExecutor(self.tenant_id, self.call_id, config.get("tools", []), self.state, caller or tool_caller())
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ loading
    @classmethod
    async def open(cls, call_id: str, tenant_id: str, caller: ToolCaller | None = None, config_override: dict[str, Any] | None = None) -> AgentSession:
        cached = REGISTRY.get(call_id)
        if cached and cached.tenant_id == tenant_id:
            return cached
        async with sessionmaker()() as s:
            call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
            if not call:
                raise ApiError(404, "call_not_found", "Call not found")
            if config_override is not None:
                config = config_override
            else:
                version = await s.get(AgentVersion, call.agent_version_id)
                config = version.config if version else {}
            tenant = await s.get(Tenant, tenant_id)
            seq = await s.scalar(select(func.max(CallEvent.seq)).where(CallEvent.call_id == call_id)) or 0
            meta = call.meta or {}
            live = dict(meta.get("live") or {})
            base_persona = dict(config.get("persona") or {})
            if live.get("persona_id"):  # call-start or live persona override
                row = await s.get(Persona, live["persona_id"])
                if row is not None and row.tenant_id == tenant_id:
                    config = {**config, "persona": persona_dict(row)}
            state = CallState(**meta["state"]) if meta.get("state") else CallState()
            state.ended = state.ended or call.ended_at is not None
            sess = cls(call=call, config=config, tenant_name=tenant.name if tenant else tenant_id, caller=caller,
                       history=list(meta.get("history", [])), state=state, seq=seq, live=live, context=meta.get("context"))
            sess.base_persona = base_persona
        if not sess.state.ended:
            REGISTRY[call_id] = sess
        return sess

    # ------------------------------------------------------------ persistence helpers
    async def _event(self, kind: str, text: str | None = None, data: dict[str, Any] | None = None) -> None:
        self.seq += 1
        ev = CallEvent(tenant_id=self.tenant_id, call_id=self.call_id, seq=self.seq, kind=kind, text=text, data=data or {})
        async with sessionmaker()() as s:
            s.add(ev)
            await s.commit()
        bus.publish(self.tenant_id, f"call:{self.call_id}", "call.event",
                    {"call_id": self.call_id, "seq": self.seq, "kind": kind, "text": text, "data": data or {}})

    async def _persist(self) -> None:
        async with sessionmaker()() as s:
            call = await s.get(Call, self.call_id)
            if not call:
                return
            call.turn_count = self.state.turns
            call.tokens_in, call.tokens_out = self.state.tokens_in, self.state.tokens_out
            call.llm_cost_usd = round(self.state.cost_usd, 6)
            call.caller_ref = self.state.verified_member_ref
            if self.state.latencies_ms:
                call.latency_p50_ms = int(statistics.median(self.state.latencies_ms))
            call.meta = {**(call.meta or {}), "state": asdict(self.state), "history": self.history[-60:], "live": self.live}
            await s.commit()

    # ------------------------------------------------------------ live settings
    def turn_settings(self):  # noqa: ANN201
        return effective_turn(self.config, self.live)

    def settings(self) -> dict[str, Any]:
        return settings_view(self.config.get("persona") or {}, self.turn_settings())

    async def switch_persona(self, persona: dict[str, Any] | None) -> None:
        """Live persona switch (PER-04); None restores the agent's own persona."""
        persona = persona or self.base_persona
        self.config = {**self.config, "persona": persona}
        self.live["persona_id"] = persona.get("id") if persona is not self.base_persona else None
        await self._event("system", f"Persona switched to {persona.get('name', 'default')}", {"persona_id": persona.get("id")})
        await self._persist()

    async def change_turn_detection(self, patch: dict[str, Any]) -> None:
        merged = {**(self.live.get("turn_detection") or {}), **patch}
        self.live["turn_detection"] = merged
        t = self.turn_settings()
        label = "Semantic" if t.mode == "semantic" else "Normal"
        await self._event("system", f"Turn detection: {label} detection, {t.min_silence_ms} ms silence", {"turn_detection": t.to_dict()})
        await self._persist()

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> str:
        persona = self.config.get("persona", {})
        if self.config.get("mode") == "outbound":  # OB-02: the agent speaks first with the persona opening
            greeting = outbound.render_opening(persona, self.context, self.tenant_name)
        else:
            greeting = f"{persona.get('greeting', '').strip()} {persona.get('disclosure', '').strip()}".strip()
        self.history.append({"role": "assistant", "content": greeting})
        await self._event("assistant", greeting, {"greeting": True})
        await self._persist()
        return greeting

    async def end(self, reason: str) -> None:
        """Idempotent (RT-08)."""
        if self.state.ended:
            return
        self.state.ended = True
        self.end_reason = reason
        REGISTRY.pop(self.call_id, None)
        await self._persist()
        async with sessionmaker()() as s:
            call = await s.get(Call, self.call_id)
            if call is None or call.ended_at is not None:
                return
            call.ended_at, call.end_reason = utcnow(), reason
            call.status = "ended"
            if self.state.escalated:
                call.outcome = "escalated"
            if not self.is_eval:
                await post_call_analysis().request(s, self.tenant_id, self.call_id, "call_ended")
            await s.commit()
            data = {"call_id": self.call_id, "status": call.status, "outcome": call.outcome, "end_reason": reason}
        bus.publish(self.tenant_id, f"call:{self.call_id}", "call.ended", data)
        if not self.is_eval:
            bus.publish(self.tenant_id, "dashboard", "call.ended", data)

    async def escalate(self, category: str, detail: str) -> None:
        if self.state.escalated:  # ES-08
            return
        self.state.escalated = True
        self.state.escalation_id = await handoff_desk().open(
            self.tenant_id, self.call_id, self.agent_id, category, detail,
            list(self.state.tools_used), self.state.verified_member_ref, is_eval=self.is_eval,
        )
        await self._event("system", f"Escalated: {category.replace('_', ' ')}", {"escalation_id": self.state.escalation_id, "category": category, "detail": detail})

    async def _say(self, text: str, data: dict[str, Any] | None = None) -> str:
        self.history.append({"role": "assistant", "content": text})
        await self._event("assistant", text, data or {})
        return text

    async def announce(self, text: str, data: dict[str, Any] | None = None) -> str:
        """A line the runtime says outside a caller turn (silence reminder, closing lines); recorded like any assistant line."""
        await self._say(text, data)
        await self._persist()
        return text

    # ------------------------------------------------------------ turn
    async def respond(self, user_text: str) -> AsyncIterator[str]:
        async with self._lock:
            async for chunk in self._turn(user_text):
                yield chunk

    async def reply(self, user_text: str) -> str:
        parts = [c async for c in self.respond(user_text)]
        return " ".join(p.strip() for p in parts if p.strip())

    async def _turn(self, user_text: str) -> AsyncIterator[str]:
        text = user_text.strip()
        if not text or self.state.ended:
            return
        self.state.turns += 1
        self.history.append({"role": "user", "content": text})
        await self._event("user", text)
        policy = self.config.get("policy", {})

        if self.state.escalated:  # RT-02
            yield await self._say(policy.get("holding_message") or "A specialist will be with you shortly.")
            await self._persist()
            return

        if endings.is_farewell(text):  # CE-02: no model needed to close a call the caller has finished
            yield await self._say(GOODBYE, {"farewell": True})
            await self._persist()
            await self.end("farewell")
            return

        if policy.get("safety_screen", True) and safety.safety_match(text):  # ES-01
            yield await self._say(safety.SAFETY_MESSAGE, {"safety": True})
            await self.escalate("safety", "Caller used emergency or self-harm language")
            await self._persist()
            await self.end("handoff")  # CE-01
            return

        handoff = policy.get("handoff_message") or "I'm connecting you with a specialist."
        override = (self.config.get("models") or {}).get("realtime")
        schemas = all_schemas(self.config.get("tools", []))
        spoken = ""
        rounds = 0
        filler_done = False
        turn_started = time.perf_counter()
        first_chunk_ms: int | None = None

        while True:
            system = system_prompt(self.config, self.tenant_name, self.state.verified_member_ref, self.started_at, self.context)
            messages = [{"role": "system", "content": system}, *_trim_history(self.history)]
            result = None
            round_text = ""
            try:
                async for ev in gateway().stream_chat("realtime", messages, schemas, override):
                    if ev["type"] == "text":
                        if first_chunk_ms is None:
                            first_chunk_ms = int((time.perf_counter() - turn_started) * 1000)
                        round_text += ev["text"]
                        yield ev["text"]
                    else:
                        result = ev["result"]
            except (LLMError, Exception) as exc:  # noqa: BLE001 - RT-06
                log.warning("realtime LLM failed on call %s: %s", self.call_id, exc)
                if spoken or round_text:
                    self.history.append({"role": "assistant", "content": (spoken + round_text).strip()})
                yield await self._say(APOLOGY_OUTAGE, {"error": "llm_unavailable"})
                await self.escalate("other", "The assistant's language model was unavailable")
                await self._persist()
                await self.end("handoff")  # CE-01
                return
            assert result is not None
            self.state.tokens_in += result.usage.input_tokens
            self.state.tokens_out += result.usage.output_tokens
            self.state.cost_usd += result.usage.cost_usd
            spoken += round_text

            if not result.tool_calls:
                break
            if rounds >= MAX_TOOL_ROUNDS:  # RT-04
                if not spoken.strip():
                    spoken = APOLOGY_TOOLS
                    yield APOLOGY_TOOLS
                break
            rounds += 1
            if self.channel == "voice" and policy.get("voice_filler", True) and not filler_done and not round_text.strip():
                filler_done = True
                yield FILLER
                spoken += FILLER + " "
            self.history.append({
                "role": "assistant", "content": round_text or None,
                "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments or "{}"}} for tc in result.tool_calls],
            })
            outputs = await asyncio.gather(*(self._run_tool(tc.id, tc.name, tc.arguments) for tc in result.tool_calls))
            for tc, output in zip(result.tool_calls, outputs):
                self.history.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            if self.state.escalated:  # model called escalate_to_human: runtime speaks the handoff
                if spoken.strip():
                    await self._event("assistant", spoken.strip(), {"latency_ms": first_chunk_ms})
                    self.history.append({"role": "assistant", "content": spoken.strip()})
                yield await self._say(handoff)
                await self._persist()
                await self.end("handoff")  # CE-01
                return

        final = spoken.strip()
        if self.state.end_requested and not final:
            final = GOODBYE
            yield GOODBYE
        if final:
            if first_chunk_ms is not None:
                self.state.latencies_ms.append(first_chunk_ms)
            self.history.append({"role": "assistant", "content": final})
            await self._event("assistant", final, {"latency_ms": first_chunk_ms, "tokens_in": self.state.tokens_in, "tokens_out": self.state.tokens_out})

        trigger = self._post_turn_trigger(policy)
        if trigger and not self.state.escalated:
            yield await self._say(handoff)
            await self.escalate(*trigger)
        await self._persist()
        if self.state.escalated:  # a post-turn trigger fired this turn (an earlier escalation returned above)
            await self.end("handoff")  # CE-01
        elif self.state.end_requested:
            await self.end("end_call")  # RT-05

    def _post_turn_trigger(self, policy: dict[str, Any]) -> tuple[str, str] | None:
        if self.state.no_answer_streak >= 2:  # ES-02
            return "knowledge_gap", "No approved information for: " + "; ".join(self.state.no_answer_queries[-2:])
        if self.state.tool_error_streak >= 2:  # ES-03
            return "tool_failure", "Business systems returned errors twice in a row"
        if self.state.turns >= int(policy.get("max_turns", 16)):
            return "other", "Maximum number of turns reached"
        return None

    async def _run_tool(self, call_id: str, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = None
        await self._event("tool_call", None, {"tool_call_id": call_id, "name": name, "args": args if isinstance(args, dict) else arguments})
        started = time.perf_counter()
        ok = True
        if name == "search_knowledge":
            query = str((args or {}).get("query", ""))
            async with sessionmaker()() as s:
                result = await kb_search(s, self.tenant_id, list(self.config.get("knowledge_doc_ids", [])), query)
            if result.get("no_answer"):
                self.state.no_answer_streak += 1
                self.state.no_answer_queries.append(query)
            else:
                self.state.no_answer_streak = 0
            top = (result.get("results") or [{}])[0]
            self.state.tools_used.append({"name": name, "ok": True, "summary": f"Searched knowledge for '{query}': " + ("no answer" if result.get("no_answer") else f"found '{top.get('title')}'")})
        elif name == "escalate_to_human":
            a = args or {}
            category = str(a.get("reason_category") or "other")
            if category not in escalation_categories():
                category = "other"
            await self.escalate(category, str(a.get("reason_detail") or ""))
            result = {"status": "escalated", "say": self.config.get("policy", {}).get("handoff_message", "")}
        elif name == "end_call":
            self.state.end_requested = True
            result = {"status": "ending"}
        else:
            result, ok = await self.tools.execute(name, arguments)
            if name in self.tools.tools:
                self.state.tool_error_streak = 0 if ok else self.state.tool_error_streak + 1
        duration = int((time.perf_counter() - started) * 1000)
        await self._event("tool_result", None, {"tool_call_id": call_id, "name": name, "ok": ok and "error" not in result, "result": result, "duration_ms": duration})
        return truncate(result)


def escalation_categories() -> tuple[str, ...]:
    from voiceai.ports.handoff import HANDOFF_CATEGORIES as ESCALATION_CATEGORIES

    return ESCALATION_CATEGORIES
