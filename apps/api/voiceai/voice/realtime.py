"""Realtime speech-to-speech bridge: caller audio -> OpenAI Realtime -> caller, driving the shared AgentSession.

Spec: /architecture/realtime-voice.md, /decisions/adr-0008-telephony-and-realtime-voice.md, /prompts/realtime-addendum.md

Spike S4 (verification/spikes.md): Pipecat's own OpenAI Realtime service is driven by its LLM context aggregators and cannot
inject exact text or hand tool results to our AgentSession, so this module speaks the provider's WebSocket protocol directly
and uses Pipecat only for the transport, serializers and frames. The provider connection is behind a small interface so
tests run the whole bridge against a scripted fake with no network.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai import prompts
from voiceai.live import LiveControls
from voiceai.llm.gateway import Usage, gateway
from voiceai.runtime.call_floor import CallFloor
from voiceai.runtime.prompt import system_prompt
from voiceai.runtime.session import AgentSession, Decision
from voiceai.runtime.tools import all_schemas
from voiceai.voice.turn_detection import TurnSettings

log = logging.getLogger("voiceai.voice.realtime")

RATE = 24000                      # PCM16 mono, both directions
EXACT_PREFIX = "Say exactly the following text, word for word, and nothing else: "
USER_RECORDED_WAIT_S = 2.0        # a reply is stored after the transcript of the turn it answers, but never waits longer
FILLER_ON = "Before a tool call that may take a moment, say one short phrase such as 'One moment while I check that.'"
FILLER_OFF = "Do not announce tool calls."
BENIGN_ERRORS = ("response_cancel_not_active", "conversation_already_has_active_response", "item_truncate_invalid_item_id")


# ---------------------------------------------------------------- provider connection
class RealtimeConnection(Protocol):
    async def send(self, event: dict[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any] | None: ...   # None when the provider closed the socket
    async def close(self) -> None: ...


class ProviderUnavailable(Exception):
    """The Realtime service could not be reached (RV-13)."""


class WebSocketConnection:
    """The real connection: wss://api.openai.com/v1/realtime?model=<model> with a bearer key."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    @classmethod
    async def open(cls, api_key: str, model: str, base_url: str = "wss://api.openai.com/v1/realtime") -> WebSocketConnection:
        from websockets.asyncio.client import connect

        try:
            ws = await asyncio.wait_for(connect(f"{base_url}?model={model}", additional_headers={"Authorization": f"Bearer {api_key}"}), 10)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(str(exc)) from exc
        return cls(ws)

    async def send(self, event: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(event))

    async def recv(self) -> dict[str, Any] | None:
        try:
            raw = await self._ws.recv()
        except Exception:  # noqa: BLE001 - closed or broken: the bridge treats both as "provider gone"
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {"type": "unparsed"}

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()


Connector = Callable[[], Awaitable[RealtimeConnection]]


async def connect_openai(api_key: str, model_ref: str) -> RealtimeConnection:
    from voiceai.config import get_settings

    return await WebSocketConnection.open(api_key, model_ref.split(":", 1)[-1], get_settings().openai_realtime_url)


# ---------------------------------------------------------------- session payloads (pure, tested)
def turn_detection(turn: TurnSettings, welcoming: bool = False, closing: bool = False) -> dict[str, Any]:
    """RV-10: the agent's turn-detection settings in the service's terms.

    While the welcome or a closing line plays nothing may interrupt it and nothing is answered. With interruptions
    disallowed the bridge asks for each reply itself, so the service never cuts the agent off.
    """
    quiet = welcoming or closing
    interrupt = bool(turn.allow_interruptions) and not quiet
    create = bool(turn.allow_interruptions) and not quiet
    if turn.mode == "semantic":
        return {"type": "semantic_vad", "eagerness": "auto", "create_response": create, "interrupt_response": interrupt}
    return {
        "type": "server_vad", "silence_duration_ms": int(turn.min_silence_ms), "prefix_padding_ms": 300,
        "create_response": create, "interrupt_response": interrupt,
    }


def realtime_tools(config: dict[str, Any]) -> list[dict[str, Any]]:
    """RV-04: built-in tools plus the agent's tools, same names and schemas as the text channel, in the service's tool format."""
    out = []
    for item in all_schemas(config.get("tools", [])):
        fn = item["function"]
        out.append({"type": "function", "name": fn["name"], "description": fn.get("description", ""), "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
    return out


def realtime_instructions(session: AgentSession) -> str:
    """RV-04: the assembled system prompt of the agent version followed by the realtime addendum (both loaded from specs/prompts)."""
    policy = session.config.get("policy", {})
    base = system_prompt(session.config, session.tenant_name, session.state.verified_member_ref, session.started_at, session.context)
    addendum = prompts.render("realtime-addendum", filler_instruction=FILLER_ON if policy.get("voice_filler", True) else FILLER_OFF)
    return f"{base}\n\n{addendum}".strip()


def session_update(session: AgentSession, turn: TurnSettings, *, welcoming: bool = False, closing: bool = False) -> dict[str, Any]:
    g = gateway()
    voices = g.speech_voices()
    voice = ((session.config.get("voice") or {}).get("realtime") or {}).get("voice") or (voices[0] if voices else None)
    audio_out: dict[str, Any] = {"format": {"type": "audio/pcm", "rate": RATE}}
    if voice:
        audio_out["voice"] = voice
    transcription = g.speech_params().get("transcription_model")
    audio_in: dict[str, Any] = {"format": {"type": "audio/pcm", "rate": RATE}, "turn_detection": turn_detection(turn, welcoming, closing)}
    if transcription:
        audio_in["transcription"] = {"model": transcription}
    return {
        "type": "session.update",
        "session": {
            "type": "realtime", "output_modalities": ["audio"], "instructions": realtime_instructions(session),
            "audio": {"input": audio_in, "output": audio_out},
            "tools": realtime_tools(session.config), "tool_choice": "auto",
        },
    }


def usage_from(raw: dict[str, Any] | None) -> Usage:
    raw = raw or {}
    in_d, out_d = raw.get("input_token_details") or {}, raw.get("output_token_details") or {}
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0), output_tokens=int(raw.get("output_tokens") or 0),
        audio_input_tokens=int(in_d.get("audio_tokens") or 0), audio_output_tokens=int(out_d.get("audio_tokens") or 0),
    )


@dataclass
class _Resp:
    id: str
    exact: str | None = None        # set for lines the platform asked the service to read verbatim
    suppressed: bool = False        # cancelled because a fixed line replaces it: its text is never stored
    text: str = ""                  # transcript of what the service said
    item_id: str = ""
    audio_bytes: int = 0
    first_audio_at: float | None = None
    latency_ms: int | None = None
    waits_for_user: bool = False    # created before the transcript of the caller turn it answers arrived: store it after that transcript
    calls: list[asyncio.Task[None]] = field(default_factory=list)


class RealtimeBridge(FrameProcessor):
    """Sits between the transport input and output: audio in, audio out, and the call's rules around the model."""

    FINISH_WAIT_S = 10.0
    FINISH_GRACE_S = 0.3   # audio may still be on its way to the transport when the closing response is done

    def __init__(
        self, session: AgentSession, controls: LiveControls, conn: RealtimeConnection,
        on_end: Callable[[str], Awaitable[None]], *, send_ready: bool = True, **kwargs: Any,  # noqa: ANN401
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.controls = controls
        self.conn = conn
        self.on_end = on_end
        self.send_ready = send_ready
        self._resampler = create_stream_resampler()
        self._reader: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[Any]] = set()
        self._resp: dict[str, _Resp] = {}
        self._active: str | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._user_recorded = asyncio.Event()
        self._user_recorded.set()
        self._bot_stopped = asyncio.Event()
        self._bot_stopped.set()
        self._exact_queue: list[str] = []  # lines asked for verbatim, in order (fallback when the service does not echo metadata)
        self._speech_stopped_at: float | None = None
        self._hold_pending = False
        # the protected welcome, the silence and call-length clock and the closing state (RV-07, RV-11, CE-04..CE-06)
        self.floor = CallFloor(session, controls, self, on_end)

    # ------------------------------------------------------------ helpers
    def _tools_running(self) -> bool:
        return any(not t.done() for r in self._resp.values() for t in r.calls)

    async def settle(self) -> None:
        """Wait for background work (tool calls, fixed lines, endings) started so far; used by tests."""
        while True:
            await self.floor.settle()
            pending = [t for t in self._background if not t.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _send(self, event: dict[str, Any]) -> None:
        try:
            await self.conn.send(event)
        except Exception as exc:  # noqa: BLE001
            log.warning("realtime send failed: %s", exc)
            await self._provider_lost()

    async def _update_session(self) -> None:
        await self._send(session_update(self.session, self.controls.turn, welcoming=self.floor.welcoming, closing=self.floor.closing))

    # ------------------------------------------------------------ the floor's Stage
    def working(self) -> bool:
        return self._active is not None or self._tools_running()

    async def say(self, text: str) -> None:
        await self._say_exact(text)

    async def drained(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._idle.wait(), self.FINISH_WAIT_S)  # the closing line was fully produced
        if not self.floor.bot_speaking:
            await asyncio.sleep(self.FINISH_GRACE_S)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._bot_stopped.wait(), self.FINISH_WAIT_S)

    async def guard_changed(self) -> None:
        await self._update_session()  # welcome or closing protection: the service's turn detection follows

    # ------------------------------------------------------------ startup and welcome
    async def start(self) -> None:
        """Open the session: tools, instructions, voice and turn detection; then read provider events."""
        self.floor.start()
        await self._update_session()
        self._reader = asyncio.ensure_future(self._read_loop())

    async def greet(self) -> None:
        """RV-07: the welcome is spoken once, as exact text, and nothing interrupts or answers during it."""
        async def opening() -> str:
            if self.send_ready:
                await self.push_frame(OutputTransportMessageUrgentFrame(message={"type": "ready"}))
            return await self.session.start()

        await self.floor.welcome(opening)  # protected first: no interruption, no automatic reply

    # ------------------------------------------------------------ audio in
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self.start()
            return
        if isinstance(frame, InputAudioRawFrame):
            if not self.floor.closing:
                await self._audio_in(frame)
            return
        if isinstance(frame, InputTransportMessageFrame):
            if isinstance(frame.message, dict) and frame.message.get("type") == "hangup":
                await self.floor.end("hangup")
            return
        if isinstance(frame, BotStartedSpeakingFrame):
            self.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.on_bot_stopped()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self.shutdown()
        await self.push_frame(frame, direction)

    async def _audio_in(self, frame: InputAudioRawFrame) -> None:
        audio = frame.audio
        if frame.sample_rate != RATE:
            audio = await self._resampler.resample(audio, frame.sample_rate, RATE)
        if audio:
            await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(audio).decode("ascii")})

    async def shutdown(self) -> None:
        await self.floor.stop()
        for task in (self._reader, *self._background):
            if task and not task.done() and task is not asyncio.current_task():
                task.cancel()
        await self.conn.close()

    # ------------------------------------------------------------ bot speaking (from the output transport)
    def on_bot_started(self) -> None:
        self._bot_stopped.clear()
        self.floor.bot_started()

    async def on_bot_stopped(self) -> None:
        self._bot_stopped.set()
        self.floor.bot_stopped(waiting=self._active is None and not self.floor.welcoming)

    # ------------------------------------------------------------ provider events
    async def _read_loop(self) -> None:
        try:
            while True:
                evt = await self.conn.recv()
                if evt is None:
                    break
                await self.handle_event(evt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("realtime reader failed")
        await self._provider_lost()

    async def handle_event(self, evt: dict[str, Any]) -> None:
        """One provider event (also called directly by tests)."""
        kind = evt.get("type", "")
        if kind == "response.created":
            await self._on_response_created(evt["response"])
        elif kind == "response.output_audio.delta":
            await self._on_audio_delta(evt)
        elif kind == "response.output_audio_transcript.delta":
            resp = self._resp.get(evt.get("response_id", ""))
            if resp is not None:
                resp.text += evt.get("delta", "")
        elif kind == "response.function_call_arguments.done":
            self._on_function_call(evt)
        elif kind == "response.done":
            await self._on_response_done(evt["response"])
        elif kind == "input_audio_buffer.speech_started":
            await self._on_speech_started()
        elif kind == "input_audio_buffer.speech_stopped":
            await self._on_speech_stopped()
        elif kind == "conversation.item.input_audio_transcription.completed":
            await self._on_user_transcript(evt.get("transcript", ""))
        elif kind == "conversation.item.input_audio_transcription.failed":
            self._user_recorded.set()
        elif kind == "error":
            error = evt.get("error") or {}
            if error.get("code") in BENIGN_ERRORS:
                log.debug("realtime: %s", error.get("message"))
            else:
                log.warning("realtime error: %s", error)

    async def _on_response_created(self, response: dict[str, Any]) -> None:
        rid = response.get("id", "")
        resp = self._resp.setdefault(rid, _Resp(rid))
        meta = response.get("metadata")
        exact = (meta.get("kind") == "exact") if meta is not None else bool(self._exact_queue)
        if exact:
            resp.exact = self._exact_queue.pop(0) if self._exact_queue else (meta or {}).get("text", "")
        resp.waits_for_user = not self._user_recorded.is_set()
        self._active = rid
        self._idle.clear()
        self.floor.reply_started()

    async def _on_audio_delta(self, evt: dict[str, Any]) -> None:
        rid = evt.get("response_id", "")
        resp = self._resp.setdefault(rid, _Resp(rid))
        if resp.suppressed:
            return
        audio = base64.b64decode(evt.get("delta", ""))
        if not audio:
            return
        if resp.first_audio_at is None:
            resp.first_audio_at = time.perf_counter()
            resp.item_id = evt.get("item_id", "")
            if self._speech_stopped_at is not None and resp.exact is None:
                resp.latency_ms = int((resp.first_audio_at - self._speech_stopped_at) * 1000)
            await self.push_frame(TTSStartedFrame())
        resp.audio_bytes += len(audio)
        await self.push_frame(TTSAudioRawFrame(audio=audio, sample_rate=RATE, num_channels=1))

    async def _on_speech_started(self) -> None:
        self.floor.caller_started()
        self._user_recorded.clear()
        if not self.floor.may_interrupt(self.controls.turn.allow_interruptions):
            return
        if self._active is not None:  # VO-03 for the realtime pipeline: drop queued audio and tell the service what was heard
            await self._interrupt()

    async def _on_speech_stopped(self) -> None:
        self._speech_stopped_at = time.perf_counter()
        if not self.controls.turn.allow_interruptions and self.floor.listening:
            await self._respond_when_free()  # hold mode: the service never replies by itself

    async def _respond_when_free(self) -> None:
        if self.working():
            self._hold_pending = True
            return
        self._hold_pending = False
        await self._send({"type": "response.create"})

    async def _interrupt(self) -> None:
        resp = self._resp.get(self._active or "")
        if resp is None or resp.exact is not None:
            return
        played_ms = 0
        if resp.first_audio_at is not None:
            total_ms = resp.audio_bytes / 2 / RATE * 1000
            played_ms = int(min(total_ms, (time.perf_counter() - resp.first_audio_at) * 1000))
        await self.broadcast_interruption()
        await self._send({"type": "response.cancel"})
        if resp.item_id:
            await self._send({"type": "conversation.item.truncate", "item_id": resp.item_id, "content_index": 0, "audio_end_ms": played_ms})

    async def _on_user_transcript(self, text: str) -> None:
        text = (text or "").strip()
        if self.floor.closing:
            return
        if self.floor.welcoming:  # VO-08: heard during the welcome (often our own echo): not a caller turn
            log.debug("dropping caller turn heard during the welcome: %r", text)
            self._user_recorded.set()
            return
        if not text:
            self._user_recorded.set()
            return
        decision = await self.session.caller_turn(text)
        self._user_recorded.set()
        if decision.say is not None:  # spawned: it waits for provider events this reader loop has to keep delivering
            self._spawn(self._replace_reply(decision))

    async def _replace_reply(self, decision: Decision) -> None:
        """RV-08: a fixed line replaces whatever the model was about to say."""
        await self._cancel_active(suppress=True)
        await self._carry_out(decision)

    async def _carry_out(self, decision: Decision) -> None:
        """Speak a decision's exact line and, when it ends the call, close once the line was spoken."""
        await self.session.commit(decision)
        if decision.end:
            await self.floor.begin_closing()
        if decision.say is not None:
            await self._say_exact(decision.say)
        if decision.end:
            self.floor.finish_after_drain(decision.end)

    # ------------------------------------------------------------ tool calls
    def _on_function_call(self, evt: dict[str, Any]) -> None:
        rid = evt.get("response_id", "")
        resp = self._resp.setdefault(rid, _Resp(rid))
        resp.calls.append(self._spawn(self._run_call(resp, evt.get("call_id", ""), evt.get("name", ""), evt.get("arguments") or "{}")))

    async def _after_user_transcript(self, resp: _Resp) -> None:
        if resp.waits_for_user:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._user_recorded.wait(), USER_RECORDED_WAIT_S)

    async def _run_call(self, resp: _Resp, call_id: str, name: str, arguments: str) -> None:
        await self._after_user_transcript(resp)
        decision = await self.session.tool_requested(name, arguments, call_id)  # RV-05: gate and round limit
        if decision.refresh:  # the prompt carries the verification status
            await self._update_session()
        await self._send({"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": call_id, "output": decision.output}})

    async def _after_tools(self, resp: _Resp, status: str, spoke: bool) -> None:
        await asyncio.gather(*resp.calls, return_exceptions=True)
        if self.floor.closing or status == "cancelled":
            return
        decision = await self.session.tools_finished(spoke)
        if decision.model_turn:
            await self._send({"type": "response.create"})
            return
        if decision.end == "handoff":  # RV-09: the hand-off message replaces anything still playing
            await self._cancel_active(suppress=False)
        await self._carry_out(decision)

    # ------------------------------------------------------------ responses
    async def _on_response_done(self, response: dict[str, Any]) -> None:
        rid = response.get("id", "")
        resp = self._resp.pop(rid, None) or _Resp(rid)
        status = response.get("status", "completed")
        usage = usage_from(response.get("usage"))
        usage.cost_usd = gateway().usage_cost(gateway().speech_ref(((self.session.config.get("models") or {}).get("speech"))), usage)
        if self._active == rid:
            self._active = None
            self._idle.set()
        if not resp.text:  # the transcript can also arrive inside the finished items
            for item in response.get("output") or []:
                for part in item.get("content") or []:
                    resp.text += part.get("transcript") or ""
        spoke = bool(resp.text.strip())
        decision = Decision()
        if resp.exact is not None or resp.suppressed:
            await self.session.reply_finished("", usage=usage, decide=False)  # the line was stored when the platform chose it
            if resp.exact is not None and self.floor.welcoming:
                self.floor.welcome_produced()
        else:
            await self._after_user_transcript(resp)
            decide = not resp.calls and status == "completed" and not self.floor.closing  # ES-02, ES-03, max turns, end_call
            decision = await self.session.reply_finished(
                resp.text, resp.latency_ms, usage, interrupted=(status == "cancelled" and spoke), decide=decide,
            )
        if self._hold_pending and not resp.calls and not self.floor.closing:
            await self._respond_when_free()
        if resp.calls:
            self._spawn(self._after_tools(resp, status, spoke))
        elif decision.end:
            await self._carry_out(decision)
        if self._active is None:
            self.floor.settled()

    async def _cancel_active(self, suppress: bool) -> None:
        rid = self._active
        if rid is None:
            return
        resp = self._resp.get(rid)
        if resp is not None and suppress:
            resp.suppressed = True
        await self.broadcast_interruption()
        await self._send({"type": "response.cancel"})
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._idle.wait(), 2.0)

    async def _say_exact(self, text: str) -> None:
        """Have the service read `text` verbatim, as its own reply (welcome, farewell, safety, hand-off, silence lines)."""
        if not self._idle.is_set():
            await self._cancel_active(suppress=True)
        self._exact_queue.append(text)
        await self._send({
            "type": "response.create",
            "response": {
                "output_modalities": ["audio"], "tool_choice": "none", "instructions": EXACT_PREFIX + text,
                "metadata": {"kind": "exact", "text": text[:400]},
            },
        })

    # ------------------------------------------------------------ ending
    async def _provider_lost(self) -> None:
        """RV-13: the service went away mid-call."""
        if self.floor.closing:
            return
        await self.floor.begin_closing(tell_stage=False)  # nothing can be sent any more
        log.warning("realtime provider connection lost on call %s", self.session.call_id)
        with contextlib.suppress(Exception):
            await self.session.escalate("other", "The realtime voice service was unavailable")
        await self.floor.end("error")
