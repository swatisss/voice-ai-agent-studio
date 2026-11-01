"""The session a routed voice conversation runs on: the front desk until the supervisor picks an agent, then that agent.

Spec: /architecture/supervisor-routing.md (Conversations, Decision), /architecture/agent-transfer.md, /api/voice-protocol.md

Both voice pipelines drive an AgentSession-shaped object. `ConversationSession` is that object for a conversation: during
the front-desk phase it greets, records and routes caller turns itself; once a segment exists every call is the segment's
AgentSession's, and the running pipeline follows when the segment changes.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from voiceai import conversations
from voiceai.call_settings import CallSettings
from voiceai.db import sessionmaker
from voiceai.live import SettingsChange
from voiceai.models import Conversation
from voiceai.routing import front_desk
from voiceai.runtime.session import AgentSession, Decision
from voiceai.runtime.state import CallState

log = logging.getLogger("voiceai.routing.voice")

CONNECTING_AFTER_S = 0.3  # say the connecting message when routing takes longer than this (cascade)


class ConversationSession:
    def __init__(self, conv: Conversation, config: dict[str, Any], connecting: str, app: Any) -> None:  # noqa: ANN401
        self.conversation_id = conv.id
        self.tenant_id = conv.tenant_id
        self.channel = "voice"
        self.app = app
        self._front_config = config
        self._front_settings = CallSettings.of(config)
        self._front_state = CallState()
        self._front_history: list[dict[str, Any]] = []
        self.connecting = connecting
        self.agent: AgentSession | None = None
        self._listeners: list[Callable[[SettingsChange], Awaitable[None]]] = []
        self._unsubs: list[Callable[[], None]] = []
        self.end_reason: str | None = None

    @classmethod
    async def open(cls, conv: Conversation, app: Any) -> ConversationSession:  # noqa: ANN401
        async with sessionmaker()() as s:
            config = await conversations.front_desk_config(s, conv)
            fd = await front_desk.load(s, conv.tenant_id)
        sess = cls(conv, config, fd.connecting_message, app)
        if conv.current_call_id:  # reconnecting to a conversation that already has an agent
            await sess._attach(await AgentSession.open(conv.current_call_id, conv.tenant_id, app=app))
        return sess

    # ------------------------------------------------------------ what the pipelines read
    @property
    def config(self) -> dict[str, Any]:
        return self.agent.config if self.agent else self._front_config

    @property
    def call_settings(self) -> CallSettings:
        return self.agent.call_settings if self.agent else self._front_settings

    @property
    def state(self) -> CallState:
        return self.agent.state if self.agent else self._front_state

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.agent.history if self.agent else self._front_history

    @property
    def call_id(self) -> str:
        return self.agent.call_id if self.agent else self.conversation_id

    def turn_settings(self):  # noqa: ANN201
        return self.call_settings.turn

    def prompt(self) -> str:
        if self.agent:
            return self.agent.prompt()
        return ("You are the front desk of a health plan's support line. You never answer questions yourself. "
                f"Whatever the caller says, reply only with exactly: \"{self.connecting}\"")

    def subscribe(self, listener: Callable[[SettingsChange], Awaitable[None]]) -> Callable[[], None]:
        self._listeners.append(listener)
        if self.agent:
            self._unsubs.append(self.agent.subscribe(listener))

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
            for u in self._unsubs:
                u()

        return unsubscribe

    async def _attach(self, agent: AgentSession) -> None:
        self.agent = agent
        for listener in self._listeners:
            self._unsubs.append(agent.subscribe(listener))

    # ------------------------------------------------------------ the front desk
    async def _front_line(self, text: str) -> str:
        self._front_history.append({"role": "assistant", "content": text})
        return text

    async def start(self) -> str:
        if self.agent:
            return await self.agent.start()
        async with sessionmaker()() as s:
            conv = await s.get(Conversation, self.conversation_id)
            events = (conv.settings or {}).get("front_desk_events") or []
        greeting = events[0]["text"] if events else ""
        return await self._front_line(greeting)

    async def _route(self, text: str) -> dict[str, Any]:
        self._front_history.append({"role": "user", "content": text})
        out = await conversations.front_desk_turn(self.conversation_id, self.tenant_id, text, self.app)
        if out["kind"] == "routed":
            await self._attach(out["session"])
        else:
            await self._front_line(out["line"])
        return out

    async def _follow_transfer(self) -> AgentSession | None:
        """XFR-06: after a transfer the same socket, voice and pipeline continue with the next segment."""
        if self.agent is not None and self.agent.transferred_to is not None:
            nxt = self.agent.transferred_to
            for u in self._unsubs:
                u()
            self._unsubs = []
            await self._attach(nxt)
            return nxt
        return None

    @property
    def transfer_available(self) -> bool:
        return bool(self.agent and self.agent.transfer_available)

    async def respond(self, text: str) -> AsyncIterator[str]:
        """The cascade's turn: route first while at the front desk, then the agent answers (with its intro)."""
        if self.agent:
            async for chunk in self.agent.respond(text):
                yield chunk
            while (nxt := await self._follow_transfer()) is not None:
                async for chunk in nxt.respond(getattr(nxt, "carried_caller_line", None) or text):
                    yield chunk
            return
        task = asyncio.ensure_future(self._route(text))
        done, _ = await asyncio.wait({task}, timeout=CONNECTING_AFTER_S)
        if not done:  # Stage B is running: the caller hears the connecting message, never silence
            yield self.connecting
        out = await task
        if out["kind"] == "clarify":
            yield out["line"]
            return
        if out["kind"] == "none":
            yield out["line"]
            await self.end("error")
            return
        async for chunk in self.agent.respond(text):  # type: ignore[union-attr]
            yield chunk

    async def caller_turn(self, text: str) -> Decision:
        """The realtime pipeline's turn: a clarifying question, or the agent's intro and then its model's answer."""
        if self.agent:
            decision = await self.agent.caller_turn(text)
            return await self._continue(decision, text)
        text = text.strip()
        if not text:
            return Decision()
        out = await self._route(text)
        if out["kind"] == "clarify":
            return Decision(say=out["line"])
        if out["kind"] == "none":
            return Decision(say=out["line"], end="error")
        decision = await self.agent.caller_turn(text)  # type: ignore[union-attr]
        decision.refresh = True  # the agent's instructions and tools replace the front desk's
        return decision

    # ------------------------------------------------------------ the rest of the turn policy
    async def commit(self, decision: Decision) -> Decision:
        return await self.agent.commit(decision) if self.agent else decision

    async def tool_requested(self, name: str, arguments: str | dict[str, Any], call_id: str | None = None) -> Decision:
        if self.agent:
            return await self.agent.tool_requested(name, arguments, call_id)
        return Decision(output='{"error": "no_tools"}')

    async def reply_finished(self, text: str, latency_ms: int | None = None, usage: Any = None, interrupted: bool = False,  # noqa: ANN401
                             decide: bool = True) -> Decision:
        if self.agent:
            return await self.agent.reply_finished(text, latency_ms, usage, interrupted, decide)
        return Decision()  # the front desk's own model line (the connecting message) is not part of any transcript

    async def tools_finished(self, spoke: bool) -> Decision:
        if not self.agent:
            return Decision()
        return await self._continue(await self.agent.tools_finished(spoke), None)

    async def _continue(self, decision: Decision, text: str | None) -> Decision:
        """A decision that transferred the conversation: the next agent's intro, then its model answers."""
        if decision.transfer_to is None:
            return decision
        nxt = await self._follow_transfer()
        assert nxt is not None
        follow = await nxt.caller_turn(getattr(nxt, "carried_caller_line", None) or text or "")
        follow.refresh = True
        return follow

    async def announce(self, text: str, data: dict[str, Any] | None = None) -> str:
        return await self.agent.announce(text, data) if self.agent else await self._front_line(text)

    async def note(self, text: str, data: dict[str, Any] | None = None) -> None:
        if self.agent:
            await self.agent.note(text, data)

    async def escalate(self, category: str, detail: str) -> None:
        if self.agent:
            await self.agent.escalate(category, detail)

    async def end(self, reason: str) -> None:
        self.end_reason = reason
        if self.agent:
            await self.agent.end(reason)
            return
        self._front_state.ended = True
        await conversations.front_desk_ended(self.tenant_id, self.conversation_id, reason)
