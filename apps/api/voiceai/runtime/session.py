"""AgentSession - the shared brain for voice, text and simulation channels.

Spec: /architecture/agent-runtime.md (Turn policy), /architecture/escalation.md (Triggers), /architecture/realtime-voice.md, /architecture/knowledge.md (KN-07), /architecture/test-suites.md (Scenario memory),
/architecture/caller-verification.md, /architecture/agent-memory.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import caller_id, jobs, memory
from voiceai.db import new_id, sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.knowledge.search import retrieval as kb_retrieval
from voiceai.llm.gateway import LLMError, Usage, gateway
from voiceai import call_settings
from voiceai.call_settings import CallSettings
from voiceai.live import SettingsChange
from voiceai.models import Agent, AgentVersion, Call, CallEvent, Tenant
from voiceai.runtime import endings, escalation, outbound
from voiceai.runtime.prompt import NOT_VERIFIED, NOTHING, system_prompt
from voiceai.runtime.state import CallState
from voiceai.runtime.tools import ToolExecutor, all_schemas, truncate

log = logging.getLogger("voiceai.runtime")

MAX_TOOL_ROUNDS = 4
HISTORY_LIMIT = 30
FILLER = "One moment while I check that."
APOLOGY_OUTAGE = "I'm sorry, I'm having trouble right now. Let me connect you with someone who can help."
APOLOGY_TOOLS = "I'm sorry, I wasn't able to finish looking that up."
GOODBYE = endings.GOODBYE
HANDOFF_DEFAULT = "I'm connecting you with a specialist."
HOLDING_DEFAULT = "A specialist will be with you shortly."

REGISTRY: dict[str, AgentSession] = {}


@dataclass
class _Rule:
    """A fixed line the runtime says instead of asking a model (holding, farewell, safety) and how the call goes on."""

    text: str
    end_reason: str | None = None                  # end the session with this reason once the line was spoken
    escalate: tuple[str, str] | None = None        # (category, detail) to escalate with
    data: dict[str, Any] | None = None


@dataclass
class Decision:
    """What a channel whose model speaks for itself does next (/architecture/agent-runtime.md, Turn policy).

    `say` is an exact line the channel speaks verbatim, replacing anything the model was saying; the channel passes
    the decision to AgentSession.commit() first, which records the line (a caller-turn line is recorded only then, so a
    model reply cut off for it is stored before it). With `end`, the call ends with that reason once the line was spoken.
    """

    say: str | None = None
    end: str | None = None
    model_turn: bool = False      # let the model answer (or, after tools, continue its turn)
    output: str | None = None     # a tool call's JSON result
    refresh: bool = False         # the prompt changed (verification): rebuild the model's instructions
    rule: _Rule | None = None     # a caller-turn rule whose line commit() still has to record


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
    context: dict[str, Any] | None = None, app: Any | None = None,
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
        targets = await outbound.fetch_targets((config.get("outbound") or {}).get("targets_url", ""), app)
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
        self, *, call: Call, config: dict[str, Any], tenant_name: str, app: Any | None,
        history: list[dict[str, Any]] | None = None, state: CallState | None = None, seq: int = 0,
        live: dict[str, Any] | None = None, context: dict[str, Any] | None = None, settings: CallSettings | None = None,
    ) -> None:
        self.call_id = call.id
        self.context: dict[str, Any] = dict(context or {})  # outbound call context (OB-01)
        self.tenant_id = call.tenant_id
        self.agent_id = call.agent_id
        self.channel = call.channel
        self.is_eval = call.is_eval
        self.started_at = call.started_at or utcnow()
        self.call_settings = settings or CallSettings.of(config, live)  # effective persona, turn detection, plan (PER-07)
        self.tenant_name = tenant_name
        self.history: list[dict[str, Any]] = history or []
        self.state = state or CallState()
        self.scenario_memory: list[str] = []  # TEST-06: a test scenario's stand-in facts (simulations only, never stored)
        self.end_reason: str | None = None  # why this session ended (CE-06: the voice pipeline reports it to the browser)
        self.seq = seq
        self.tools = ToolExecutor(
            self.tenant_id, self.call_id, config.get("tools", []), self.state, app,
            knowledge_doc_ids=list(config.get("knowledge_doc_ids", [])), escalate=lambda category, detail: self.escalate(category, detail),
            handoff_message=(config.get("policy") or {}).get("handoff_message", ""),
        )
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[SettingsChange], Awaitable[None]]] = []  # the running voice pipeline (TD-09)
        self._tool_rounds = 0  # tool calls in the current caller turn of an externally driven channel (RT-12)
        self.member_profile = NOT_VERIFIED  # filled at verification for this call only (/architecture/agent-memory.md)
        self.member_memory = NOTHING

    # ------------------------------------------------------------ loading
    @classmethod
    async def open(cls, call_id: str, tenant_id: str, app: Any | None = None, config_override: dict[str, Any] | None = None) -> AgentSession:
        cached = REGISTRY.get(call_id)
        if cached and cached.tenant_id == tenant_id:
            return cached
        async with sessionmaker()() as s:
            call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
            if not call:
                raise ApiError(404, "call_not_found", "Call not found")
            settings = await call_settings.load(s, call, config_override)
            tenant = await s.get(Tenant, tenant_id)
            seq = await s.scalar(select(func.max(CallEvent.seq)).where(CallEvent.call_id == call_id)) or 0
            meta = call.meta or {}
            state = CallState(**meta["state"]) if meta.get("state") else CallState()
            state.ended = state.ended or call.ended_at is not None
            ident = meta.get("identification")
            if ident and not meta.get("state"):  # IDV-01: identified, not verified
                state.identified_member_ref, state.identified_first_name = ident.get("member_ref"), ident.get("first_name")
                state.verification_level = "identified"
                if caller_id.attested(ident) and (settings.config.get("verification") or {}).get("trust_attested_caller_id"):
                    state.verification_level = "attested"  # IDV-05
            sess = cls(call=call, config=settings.config, tenant_name=tenant.name if tenant else tenant_id, app=app,
                       history=list(meta.get("history", [])), state=state, seq=seq, context=meta.get("context"), settings=settings)
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
    @property
    def config(self) -> dict[str, Any]:
        """The agent version's config with the effective persona."""
        return self.call_settings.config

    @property
    def live(self) -> dict[str, Any]:
        return self.call_settings.live

    def turn_settings(self):  # noqa: ANN201
        return self.call_settings.turn

    def settings(self) -> dict[str, Any]:
        return self.call_settings.view()

    def subscribe(self, listener: Callable[[SettingsChange], Awaitable[None]]) -> Callable[[], None]:
        """TD-09: the voice pipeline follows live changes; returns the unsubscribe function. Ending the call drops all."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    async def _notify(self, persona_changed: bool) -> None:
        if self.state.ended:
            return
        voice = self.call_settings.cascade_voice if persona_changed else None
        change = SettingsChange(turn=self.turn_settings(), voice=voice)
        for listener in list(self._listeners):
            await listener(change)

    async def switch_persona(self, persona: dict[str, Any] | None) -> None:
        """Live persona switch (PER-04); None restores the agent's own persona."""
        self.call_settings = self.call_settings.with_persona(persona)
        persona = self.call_settings.persona
        await self._event("system", f"Persona switched to {persona.get('name', 'default')}", {"persona_id": persona.get("id")})
        await self._persist()
        await self._notify(persona_changed=True)

    async def change_turn_detection(self, patch: dict[str, Any]) -> None:
        self.call_settings = self.call_settings.with_turn(patch)
        t = self.turn_settings()
        label = "Semantic" if t.mode == "semantic" else "Normal"
        await self._event("system", f"Turn detection: {label} detection, {t.min_silence_ms} ms silence", {"turn_detection": t.to_dict()})
        await self._persist()
        await self._notify(persona_changed=False)

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
        self._listeners.clear()  # TD-09: no change reaches a pipeline after its call ended
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
                await jobs.enqueue(s, self.tenant_id, "analyze_call", {"call_id": self.call_id}, dedupe_key=f"analyze_call:{self.call_id}")
            await memory.enqueue_extraction(s, call, self.config)  # MEM-01
            await s.commit()
            data = {"call_id": self.call_id, "status": call.status, "outcome": call.outcome, "end_reason": reason}
        bus.publish(self.tenant_id, f"call:{self.call_id}", "call.ended", data)
        if not self.is_eval:
            bus.publish(self.tenant_id, "dashboard", "call.ended", data)

    async def escalate(self, category: str, detail: str) -> None:
        if self.state.escalated:  # ES-08
            return
        self.state.escalated = True
        self.state.escalation_id = await escalation.create(
            self.tenant_id, self.call_id, self.agent_id, category, detail,
            list(self.state.tools_used), self.state.verified_member_ref, is_eval=self.is_eval,
        )
        await self._event("system", f"Escalated: {category.replace('_', ' ')}", {"escalation_id": self.state.escalation_id, "category": category, "detail": detail})

    async def _say(self, text: str, data: dict[str, Any] | None = None) -> str:
        self.history.append({"role": "assistant", "content": text})
        await self._event("assistant", text, data or {})
        return text

    async def note(self, text: str, data: dict[str, Any] | None = None) -> None:
        """A system line in the call's transcript (a transfer, a setting change): not something the caller hears."""
        await self._event("system", text, data)

    async def announce(self, text: str, data: dict[str, Any] | None = None) -> str:
        """A line the runtime says outside a caller turn (silence reminder, closing lines); recorded like any assistant line."""
        await self._say(text, data)
        await self._persist()
        return text

    # ------------------------------------------------------------ turn policy (RT-11…RT-15)
    # A channel whose model produces the words itself (the realtime speech-to-speech pipeline) reports events and gets
    # decisions back. The rules are the ones _turn() applies with the platform's own text model.
    async def caller_turn(self, text: str) -> Decision:
        """A final caller transcript (RT-11): recorded, then the rules that run before any model reply."""
        text = text.strip()
        if not text or self.state.ended:
            return Decision()
        self._tool_rounds = 0
        await self._record_user(text)
        rule = self._caller_rule(text)
        if rule is None:
            return Decision(model_turn=True)
        return Decision(say=rule.text, end=rule.end_reason, rule=rule)

    async def commit(self, decision: Decision) -> Decision:
        """Record a decision's line (and its escalation) once the channel has stopped the model; idempotent."""
        if decision.rule is not None:
            rule, decision.rule = decision.rule, None
            await self._apply_rule(rule)
        return decision

    async def tool_requested(self, name: str, arguments: str | dict[str, Any], call_id: str | None = None) -> Decision:
        """One tool call (RT-12): the round limit, then the gate, execution, events, state and escalation of _turn()."""
        self._tool_rounds += 1
        if self._tool_rounds > MAX_TOOL_ROUNDS:
            return Decision(output=json.dumps({"error": "tool_round_limit"}))
        raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
        before = self.state.verified_member_ref
        async with self._lock:
            output = await self._run_tool(call_id or new_id()[:12], name, raw or "{}")
        return Decision(output=output, refresh=self.state.verified_member_ref != before)

    async def reply_finished(self, text: str, latency_ms: int | None = None, usage: Usage | None = None,
                             interrupted: bool = False, decide: bool = True) -> Decision:
        """A model reply ended (RT-13, RT-14): recorded with its usage; with `decide`, the post-turn rules.

        A reply that only carried a fixed line, was cut off, or still has tool calls running is recorded with
        `decide=False`; tool calls are followed up by tools_finished().
        """
        await self._record_reply(text, latency_ms, usage, interrupted)
        if not decide:
            return Decision()
        handoff = await self._post_turn_handoff()
        if handoff:
            return Decision(say=handoff, end="handoff")
        return await self._end_call_decision(spoke=bool(text.strip()))

    async def tools_finished(self, spoke: bool) -> Decision:
        """The tool calls of a model reply have all returned (RV-09): hand off, close, or let the model continue."""
        if self.state.escalated:  # the model called escalate_to_human: the hand-off message, then the call ends
            return Decision(say=await self.announce(self._handoff_line(), {"handoff": True}), end="handoff")
        if self.state.end_requested:
            return await self._end_call_decision(spoke)
        return Decision(model_turn=True)

    # -- the rules, shared by the policy and _turn()
    def _handoff_line(self) -> str:
        return self.config.get("policy", {}).get("handoff_message") or HANDOFF_DEFAULT

    def _caller_rule(self, text: str) -> _Rule | None:
        """The deterministic rules that run before any model reply (RT-02, CE-02, ES-01); None = let the model answer."""
        policy = self.config.get("policy", {})
        if self.state.escalated:
            return _Rule(policy.get("holding_message") or HOLDING_DEFAULT)
        if endings.is_farewell(text):
            return _Rule(GOODBYE, end_reason="farewell", data={"farewell": True})
        if policy.get("safety_screen", True) and escalation.safety_match(text):
            return _Rule(escalation.SAFETY_MESSAGE, end_reason="handoff", data={"safety": True},
                         escalate=("safety", "Caller used emergency or self-harm language"))
        return None

    async def _apply_rule(self, rule: _Rule) -> str:
        line = await self._say(rule.text, rule.data)
        if rule.escalate:
            await self.escalate(*rule.escalate)
        await self._persist()
        return line

    async def _post_turn_handoff(self) -> str | None:
        """Deterministic triggers after a reply (ES-02, ES-03, max turns): records the hand-off line and escalates."""
        trigger = self._post_turn_trigger(self.config.get("policy", {}))
        if not trigger or self.state.escalated:
            return None
        handoff = await self._say(self._handoff_line())
        await self.escalate(*trigger)
        await self._persist()
        return handoff

    async def _end_call_decision(self, spoke: bool) -> Decision:
        """RT-14: after `end_call`, a goodbye only when the model said nothing itself."""
        if not self.state.end_requested:
            return Decision()
        return Decision(say=None if spoke else await self.announce(GOODBYE), end="end_call")

    async def _record_user(self, text: str) -> None:
        self.state.turns += 1
        self.history.append({"role": "user", "content": text})
        await self._event("user", text)

    def _add_usage(self, usage: Usage | None) -> None:
        if usage is not None:  # RT-09
            self.state.tokens_in += usage.input_tokens
            self.state.tokens_out += usage.output_tokens
            self.state.cost_usd += usage.cost_usd

    async def _record_reply(self, text: str, latency_ms: int | None, usage: Usage | None, interrupted: bool) -> None:
        text = text.strip()
        self._add_usage(usage)
        if not text:
            await self._persist()
            return
        if interrupted:
            text = f"{text} [interrupted]"
        elif latency_ms is not None:
            self.state.latencies_ms.append(latency_ms)
        self.history.append({"role": "assistant", "content": text})
        await self._event("assistant", text, {"latency_ms": latency_ms, "tokens_in": self.state.tokens_in, "tokens_out": self.state.tokens_out})
        await self._persist()

    # ------------------------------------------------------------ turn
    async def respond(self, user_text: str) -> AsyncIterator[str]:
        async with self._lock:
            async for chunk in self._turn(user_text):
                yield chunk

    async def reply(self, user_text: str) -> str:
        parts = [c async for c in self.respond(user_text)]
        return " ".join(p.strip() for p in parts if p.strip())

    async def _turn(self, user_text: str) -> AsyncIterator[str]:
        """The platform's own text model as one more driver of the turn policy (CP-0018): the rules, their order and
        the stored events are the policy's; this loop streams the model, runs its tool rounds and speaks decisions."""
        text = user_text.strip()
        if not text or self.state.ended:
            return
        decision = await self.caller_turn(text)  # RT-02 holding, CE-02 farewell, ES-01 safety: no model needed
        if not decision.model_turn:
            async for line in self._carry_out(decision):
                yield line
            return

        policy = self.config.get("policy", {})
        override = (self.config.get("models") or {}).get("realtime")
        schemas = all_schemas(self.config.get("tools", []))
        spoken = ""
        rounds = 0  # RT-04 counts model rounds (several tool calls each), unlike RT-12's per-call limit
        filler_done = False
        turn_started = time.perf_counter()
        first_chunk_ms: int | None = None

        while True:
            system = self.prompt()
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
            self._add_usage(result.usage)
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
            if self.state.escalated:  # the model called escalate_to_human: what it said, then the hand-off (RV-09)
                await self.reply_finished(spoken, first_chunk_ms, decide=False)
                async for line in self._carry_out(await self.tools_finished(bool(spoken.strip()))):
                    yield line
                return

        decision = await self.reply_finished(spoken, first_chunk_ms)  # ES-02, ES-03, max turns, end_call (RT-05)
        async for line in self._carry_out(decision):
            yield line

    async def _carry_out(self, decision: Decision) -> AsyncIterator[str]:
        """Speak a decision's line and end the call when it says so (CE-01, CE-02, RT-05)."""
        await self.commit(decision)
        if decision.say is not None:
            yield decision.say
        if decision.end:
            await self.end(decision.end)

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
        was_verified = self.state.verified
        result, ok = await self.tools.run(name, arguments)
        duration = int((time.perf_counter() - started) * 1000)
        data = {"tool_call_id": call_id, "name": name, "ok": ok and "error" not in result, "result": result, "duration_ms": duration}
        if name == "search_knowledge":  # KN-07: the exact chunks, for call scoring and the call detail
            data["retrieval"] = kb_retrieval(str((args or {}).get("query", "")) if isinstance(args, dict) else "", result)
        await self._event("tool_result", None, data)
        if self.state.verified and not was_verified:
            await self._on_verified()
        return truncate(result)

    async def _on_verified(self) -> None:
        """MEM-05, MEM-06: once the caller is verified, the member profile and the member memory join the prompt."""
        if self.is_eval or self.channel == "simulation":
            if self.scenario_memory:  # TEST-06: shown like loaded facts; nothing is read from or written to member memory
                self.member_memory = "\n".join(["Facts:", *(f"- {f}" for f in self.scenario_memory)])
                await self._event("system", "Memory loaded", {"memory_used": [], "scenario_memory": len(self.scenario_memory)})
            return
        ref = self.state.verified_member_ref
        if not ref or not memory.settings_of(self.config).enabled:
            self.member_profile = NOTHING
            return
        async with sessionmaker()() as s:
            facts, episodes = await memory.load(s, self.tenant_id, self.agent_id, ref)
        self.member_memory = memory.render(facts, episodes)
        self.member_profile = caller_id.render_profile(await caller_id.profile(ref, self.tenant_id, self.call_id, self.tools.app))
        self.state.memory_used = [m.id for m in (*facts, *episodes)]
        await self._event("system", "Memory loaded", {"memory_used": self.state.memory_used})

    def prompt(self) -> str:
        """The system prompt for the next model request (all channels)."""
        return system_prompt(self.config, self.tenant_name, self.state.verified_member_ref, self.started_at, self.context,
                             identified_first_name=self.state.identified_first_name, member_profile=self.member_profile,
                             member_memory=self.member_memory)
