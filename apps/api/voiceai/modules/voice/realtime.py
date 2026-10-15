"""The realtime brain: one OpenAI Realtime model listens, thinks and speaks; our rules run on top.

Spec: /architecture/realtime-brain.md, /decisions/adr-0013-openai-realtime-brain.md,
      /architecture/turn-detection.md (On the realtime brain), /architecture/avatar.md

On this brain a video call's pipeline is

    transport.input -> FrameTap -> RealtimeGate -> user aggregator -> RealtimeTap -> OpenAI Realtime service
                    -> RealtimeBrain -> [Simli avatar] -> transport.output -> assistant aggregator

The service replaces voice-activity detection, speech-to-text, the TurnAggregator, the BrainProcessor
and text-to-speech. What stays ours is `RealtimeBrain`: it records what was said as the same call events
every channel has, screens the caller for emergencies, speaks the welcome and the closing lines, runs
the silence and length clocks and ends the call. Tools run through the conversation module's executor.

Nothing here is imported unless a call uses this brain (Pipecat's service is loaded lazily), so a
deployment without an OpenAI key, or an image without the extra, never touches it (RB-01).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    FunctionCallResultProperties,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMUpdateSettingsFrame,
    MetricsFrame,
    ProposedUserStoppedSpeakingFrame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)

from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai.core.config import get_settings
from voiceai.core.llm.gateway import gateway
from voiceai.modules.conversation.contract import (
    GOODBYE, IDLE_LINE, MAX_DURATION_LINE, REMINDER_LINE, SAFETY_MESSAGE, AgentSession,
)
from voiceai.modules.voice.controls import LiveControls
from voiceai.modules.voice.processors import BrainProcessor

log = logging.getLogger("voiceai.voice")

SPEECH_ROLE = "speech"
OPENAI_RATE = 24000                 # the model's audio, in and out
CLOSE_WAIT_S = 10.0                 # the closing words get this long to finish (CE-06)
END_DEADLINE_S = 8.0                # an ending was decided but no spoken reply followed: say the line ourselves
SERVICE_READY_WAIT_S = 5.0
RENDER_TIMEOUT_S = 6.0

#: What to do with a wording the model is given, never a paraphrase (RB-04).
SAY_EXACTLY = "Say exactly the following words, in this order, with nothing before or after, and nothing else: "


# ---------------------------------------------------------------- availability and choice (RB-01)
def realtime_unavailable_reason() -> str | None:
    """Why the realtime brain cannot serve a call here, or None when it can."""
    if not gateway().role_available(SPEECH_ROLE):
        return ("no usable model in the speech role - set OPENAI_API_KEY in apps/api/.env and restart the API "
                "(the role needs a model marked `speech: true` in models.yaml).")
    try:
        import pipecat.services.openai.realtime.llm  # noqa: F401
    except ImportError as exc:
        return f"Pipecat's OpenAI Realtime service is not installed ({exc}); run `uv sync` in apps/api."
    return None


def realtime_available() -> bool:
    return realtime_unavailable_reason() is None


def resolve_brain() -> str:
    """The brain a new video call gets: `realtime` or `pipeline` (RB-01).

    `VIDEO_BRAIN=pipeline` always wins. `auto` and `realtime` use the realtime brain when it is
    available; asking for it when it is not is not an error, the call just gets the chain and the
    reason is logged.
    """
    wanted = (get_settings().video_brain or "auto").strip().lower()
    if wanted == "pipeline":
        return "pipeline"
    why = realtime_unavailable_reason()
    if why is None:
        return "realtime"
    if wanted == "realtime":
        log.warning("VIDEO_BRAIN=realtime but the realtime brain is unavailable, using the pipeline brain: %s", why)
    else:
        log.info("video call uses the pipeline brain: %s", why)
    return "pipeline"


@dataclass(frozen=True)
class SpeechModel:
    ref: str
    model: str
    api_key: str
    prices: dict[str, Any]


def speech_model() -> SpeechModel:
    """The model of the `speech` role, from configuration, never a literal (RB-05)."""
    gw = gateway()
    ref = next(iter(gw.refs_for(SPEECH_ROLE)), "")
    provider, _, model = ref.partition(":")
    key = gw.api_key(provider) or ""
    return SpeechModel(ref=ref, model=model, api_key=key, prices=dict(gw.models.get(ref, {})))


def usage_cost(prices: dict[str, Any], prompt: int, completion: int, in_audio: int, out_audio: int) -> float:
    """Dollars for one response: text and audio tokens priced separately (RB-12)."""
    text_in, text_out = max(prompt - in_audio, 0), max(completion - out_audio, 0)
    return (
        text_in * prices.get("input", 0) + text_out * prices.get("output", 0)
        + in_audio * prices.get("input_audio", prices.get("input", 0))
        + out_audio * prices.get("output_audio", prices.get("output", 0))
    ) / 1e6


# ---------------------------------------------------------------- the session's configuration
def turn_detection_for(turn: Any) -> Any:
    """Our turn-detection settings as the model's own detector (RB-07).

    `vad` -> server voice-activity detection with the agent's silence threshold; `semantic` -> its
    semantic detection. `max_extra_wait_ms` has no equivalent and is ignored. Interruptions follow
    `allow_interruptions` (TD-07).
    """
    from pipecat.services.openai.realtime import events

    if turn.mode == "semantic":
        return events.SemanticTurnDetection(eagerness="auto", create_response=True,
                                            interrupt_response=bool(turn.allow_interruptions))

    class ServerVAD(events.TurnDetection):  # the API accepts these two; Pipecat's model omits them
        create_response: bool | None = None
        interrupt_response: bool | None = None

    return ServerVAD(silence_duration_ms=int(turn.min_silence_ms), create_response=True,
                     interrupt_response=bool(turn.allow_interruptions))


def tools_schema(schemas: list[dict[str, Any]]) -> Any:
    """Our tool schemas (OpenAI chat format) as Pipecat's standard tools."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    standard = []
    for s in schemas:
        fn = s["function"]
        params = fn.get("parameters") or {}
        standard.append(FunctionSchema(
            name=fn["name"], description=fn.get("description", ""),
            properties=params.get("properties") or {}, required=params.get("required") or [],
        ))
    return ToolsSchema(standard_tools=standard)


def session_properties(session: AgentSession, turn: Any, voice: str) -> Any:
    from pipecat.services.openai.realtime import events

    return events.SessionProperties(
        instructions=session.realtime_instructions(),
        output_modalities=["audio"],
        audio=events.AudioConfiguration(
            input=events.AudioInput(
                transcription=events.InputAudioTranscription(language="en"),
                turn_detection=turn_detection_for(turn),
            ),
            output=events.AudioOutput(voice=voice),
        ),
        tools=tools_schema(session.tool_schemas()),
    )


# ---------------------------------------------------------------- the words we render ourselves (RB-06)
async def render_speech(text: str, voice: str, api_key: str) -> bytes | None:
    """The safety message as audio, rendered by Deepgram so its wording is exact. None on any failure."""
    if not api_key:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=RENDER_TIMEOUT_S) as client:
            resp = await client.post(
                "https://api.deepgram.com/v1/speak",
                params={"model": voice, "encoding": "linear16", "sample_rate": OPENAI_RATE, "container": "none"},
                headers={"Authorization": f"Token {api_key}"}, json={"text": text},
            )
            resp.raise_for_status()
            return resp.content or None
    except Exception as exc:  # noqa: BLE001 - never let a vendor failure stop the safety handling
        log.warning("could not render the safety message: %s", type(exc).__name__)
        return None


# ---------------------------------------------------------------- the pieces of the pipeline
class RealtimeGate(FrameProcessor):
    """Stands before the model and holds back caller audio while the welcome plays or the call
    closes, so no turn can start and nothing is answered (RB-03)."""

    def __init__(self, controls: LiveControls) -> None:
        super().__init__()
        self.controls = controls
        self.closed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and (self.controls.welcoming or self.closed):
            return
        await self.push_frame(frame, direction)


class RealtimeTap(FrameProcessor):
    """Sits directly in front of the model, where its upstream frames arrive first.

    The service reports what the caller said, and its own errors, *upstream*, toward the context
    aggregator, so a processor behind it never sees them. This hands both to the brain and passes
    them on (RB-08, RB-13).
    """

    def __init__(self, brain: RealtimeBrain) -> None:
        super().__init__()
        self.brain = brain

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            return
        if direction == FrameDirection.UPSTREAM:
            if isinstance(frame, TranscriptionFrame):
                await self.brain.on_user_text(frame.text)
            elif isinstance(frame, ErrorFrame):
                await self.brain.fail(str(frame.error))
        await self.push_frame(frame, direction)


class RealtimeBrain(FrameProcessor):
    """Our rules on the model's events: record, screen, welcome, clocks, ending, cost."""

    WELCOME_GRACE_S = BrainProcessor.WELCOME_GRACE_S
    WELCOME_MIN_TIMEOUT_S = BrainProcessor.WELCOME_MIN_TIMEOUT_S
    WELCOME_SLOW_CHARS_PER_S = BrainProcessor.WELCOME_SLOW_CHARS_PER_S
    RUN_WATCHDOG = True
    WATCHDOG_TICK_S = 0.5

    def __init__(
        self, session: AgentSession, on_end: Callable[[str], Awaitable[None]], controls: LiveControls,
        service: Any, *, voice: str, prices: dict[str, Any], deepgram_key: str = "",
    ) -> None:
        super().__init__()
        self.session = session
        self.on_end = on_end
        self.controls = controls
        self.service = service
        self.voice = voice
        self.prices = prices
        self.deepgram_key = deepgram_key
        self.gate: RealtimeGate | None = None
        self.refresh_session: Callable[[], Awaitable[None]] | None = None  # set by the builder
        self._greeted = False
        self._closing = False
        self._bot_speaking = False
        self._bot_stopped = asyncio.Event()
        self._welcome_spoken = False
        self._welcome_end: asyncio.TimerHandle | None = None
        self._welcome_timeout: asyncio.TimerHandle | None = None
        self._fixed: deque[str] = deque()        # instructed lines awaiting their spoken reply: already recorded
        self._reply_open = False
        self._reply_text: list[str] = []
        self._reply_latency: int | None = None
        self._user_stopped_at: float | None = None
        self._pending_end: str | None = None     # farewell: end when the reply to it finishes
        self._end_timer: asyncio.TimerHandle | None = None
        self._safety = False
        # Record-keeping runs on one ordered worker, not inside frame handling: Pipecat cancels a
        # processor's in-flight work when an interruption arrives, and a caller's transcript lands
        # right beside one, so a database write done inline would be cancelled half way.
        self._jobs: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._pending = 0
        self._idle = asyncio.Event()
        self._idle.set()
        # silence and length clocks (CE-04, CE-05)
        self._silent_since: float | None = None
        self._reminded = False
        self._reminder_pending = False
        self._reminder_s, self._silence_end_s, self._max_call_s = 10.0, 30.0, 600.0
        self._call_started: float | None = None
        self._watchdog: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ ordered work
    def _later(self, job: Callable[[], Awaitable[None]]) -> None:
        self._pending += 1
        self._idle.clear()
        self._jobs.put_nowait(job)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._work())

    async def _work(self) -> None:
        while True:
            job = await self._jobs.get()
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one failed record must not stop the rest
                log.exception("realtime brain job failed on call %s", self.session.call_id)
            finally:
                self._pending -= 1
                if self._pending <= 0:
                    self._idle.set()

    async def drain(self, timeout: float = 3.0) -> None:
        """Wait, bounded, until everything queued has been recorded. Called when the call ends, so the
        last words are saved rather than cancelled half way."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._idle.wait(), timeout)

    def _stop_worker(self) -> None:
        task, self._worker = self._worker, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    # ------------------------------------------------------------ speaking
    @property
    def busy(self) -> bool:
        return self._bot_speaking or self._reply_open

    async def _service_ready(self) -> None:
        deadline = time.monotonic() + SERVICE_READY_WAIT_S
        while not getattr(self.service, "_api_session_ready", True) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    async def _instruct(self, text: str) -> None:
        """Have the model say exactly `text`. The caller has already recorded it (RB-04)."""
        from pipecat.services.openai.realtime import events

        await self._service_ready()
        self._fixed.append(text)
        await self.service.send_client_event(events.ResponseCreateEvent(
            response=events.ResponseProperties(instructions=SAY_EXACTLY + text, tool_choice="none")))

    async def say(self, text: str, data: dict[str, Any]) -> None:
        await self.session.announce(text, data)
        await self._instruct(text)

    async def greet(self) -> None:
        """Speak the welcome once, protected from the caller's speech until it is over (RB-03)."""
        if self._greeted:
            return
        self._greeted = True
        self.controls.welcoming = True
        self._start_clocks()
        try:
            greeting = await self.session.start()
            timeout = max(self.WELCOME_MIN_TIMEOUT_S, len(greeting) / self.WELCOME_SLOW_CHARS_PER_S)
            self._welcome_timeout = asyncio.get_running_loop().call_later(timeout, self._end_welcome)
            await self._instruct(greeting)
        except BaseException:
            self._end_welcome()
            raise

    def _end_welcome(self) -> None:
        self.controls.welcoming = False
        self._welcome_spoken = False
        for handle in (self._welcome_end, self._welcome_timeout):
            if handle:
                handle.cancel()
        self._welcome_end = self._welcome_timeout = None
        if self._silent_since is None and not self.busy:
            self._silent_since = time.monotonic()

    # ------------------------------------------------------------ clocks (CE-04, CE-05)
    def _start_clocks(self) -> None:
        policy = (getattr(self.session, "config", None) or {}).get("policy") or {}
        self._reminder_s = float(policy.get("silence_reminder_s", self._reminder_s))
        self._silence_end_s = float(policy.get("silence_end_s", self._silence_end_s))
        self._max_call_s = float(policy.get("max_call_seconds", self._max_call_s))
        self._call_started = time.monotonic()
        if self.RUN_WATCHDOG and self._watchdog is None:
            self._watchdog = asyncio.get_running_loop().create_task(self._watch())

    def _stop_clocks(self) -> None:
        task, self._watchdog = self._watchdog, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def _watch(self) -> None:
        while not self._closing:
            await asyncio.sleep(self.WATCHDOG_TICK_S)
            await self.check_clocks()

    async def check_clocks(self, now: float | None = None) -> None:
        """One tick: the call clock, the silence clock, and whether the model's connection is still there."""
        if self._closing:
            return
        task = getattr(self.service, "_receive_task", None)
        if task is not None and task.done() and self._greeted:  # the socket to the model has gone (RB-13)
            await self.fail("the connection to the speech model was lost")
            return
        now = time.monotonic() if now is None else now
        if self._call_started is not None and now - self._call_started >= self._max_call_s:
            await self._close_with(MAX_DURATION_LINE, "max_duration")
            return
        if self._silent_since is None or self.controls.welcoming or self.busy:
            return
        silent = now - self._silent_since
        if silent >= self._silence_end_s:
            await self._close_with(IDLE_LINE, "idle")
        elif silent >= self._reminder_s and not self._reminded:
            self._reminded = True
            self._reminder_pending = True
            await self.say(REMINDER_LINE, {"silence_reminder": True})

    async def _close_with(self, line: str, reason: str) -> None:
        self._closing = True
        await self.say(line, {"closing": reason})
        await self._finish(reason)

    # ------------------------------------------------------------ ending (CE-06, RB-11)
    async def _finish(self, reason: str) -> None:
        """Let the closing words play out (at most CLOSE_WAIT_S), then end the call."""
        self._closing = True
        if self.gate:
            self.gate.closed = True
        if self._end_timer:
            self._end_timer.cancel()
            self._end_timer = None
        self._bot_stopped.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._bot_stopped.wait(), CLOSE_WAIT_S)
        await self.on_end(reason)

    def arm_ending(self) -> None:
        """A tool decided the call is ending (end_call, escalate_to_human). A spoken reply normally
        follows and ends it; if none does within END_DEADLINE_S, say the line ourselves."""
        if self._closing or self._end_timer is not None:
            return
        loop = asyncio.get_running_loop()
        self._end_timer = loop.call_later(END_DEADLINE_S, lambda: asyncio.ensure_future(self._forced_ending()))

    async def _forced_ending(self) -> None:
        self._end_timer = None
        if self._closing:
            return
        self._closing = True
        st = self.session.state
        if st.escalated:
            line = (self.session.config.get("policy") or {}).get("handoff_message") or "I'm connecting you with a specialist."
            await self.say(line, {"closing": "handoff"})
            await self._finish("handoff")
        else:
            await self.say(GOODBYE, {"closing": "end_call"})
            await self._finish("end_call")

    async def fail(self, reason: str) -> None:
        """The model's connection failed: the call ends with `error`, nothing else takes over (RB-13)."""
        if self._closing:
            return
        self._closing = True
        log.error("realtime call %s failed: %s", self.session.call_id, reason[:200])
        if self.gate:
            self.gate.closed = True
        await self.on_end("error")

    async def deliver_tool_result(self, call_id: str, output: str, params: Any) -> None:
        """Give the model a tool's result and let it carry on (RB-05).

        Sent here, not through the context, for the reason `RealtimeTap` gives. Pipecat's context is
        told not to run the model and the result is marked as delivered so it is never sent twice.
        """
        from pipecat.services.openai.realtime import events

        await self.service.send_client_event(events.ConversationItemCreateEvent(
            item=events.ConversationItem(type="function_call_output", call_id=call_id, output=output)))
        done = getattr(self.service, "_completed_tool_calls", None)
        if isinstance(done, set):
            done.add(call_id)
        if not self._closing:
            await self.service.send_client_event(events.ResponseCreateEvent(
                response=events.ResponseProperties(output_modalities=["audio"])))
        await params.result_callback(output, properties=FunctionCallResultProperties(run_llm=False))

    # ------------------------------------------------------------ safety (RB-06)
    async def _safety_stop(self) -> None:
        """An emergency phrase: stop the reply in progress, speak the exact message, hand off."""
        from pipecat.services.openai.realtime import events

        if self._closing:
            return
        self._closing = True
        self._safety = True
        if self.gate:
            self.gate.closed = True
        with contextlib.suppress(Exception):
            await self.service.send_client_event(events.ResponseCancelEvent())
        await self.broadcast_interruption()
        text = SAFETY_MESSAGE  # already recorded and shown by `hear`
        audio = await render_speech(text, self.voice_for_fixed(), self.deepgram_key)
        if audio:
            await self.push_frame(TTSStartedFrame())
            step = OPENAI_RATE * 2 // 10  # 100 ms of 16-bit mono per frame
            for i in range(0, len(audio), step):
                await self.push_frame(TTSAudioRawFrame(audio=audio[i:i + step], sample_rate=OPENAI_RATE, num_channels=1))
            await self.push_frame(TTSStoppedFrame())
        else:  # no way to render it: the model is told to say it (the text is still recorded and shown)
            await self._instruct(text)
        await self._finish("handoff")

    def voice_for_fixed(self) -> str:
        return str((self.session.config.get("persona") or {}).get("voice") or "aura-2-thalia-en")

    # ------------------------------------------------------------ the model's events
    async def on_user_text(self, text: str) -> None:
        if self._closing or self.controls.welcoming:
            return  # heard during the welcome (often our own echo) or while closing: not a caller turn
        self._later(lambda: self._handle_user_text(text))

    async def _handle_user_text(self, text: str) -> None:
        if self._closing:
            return
        verdict = await self.session.hear(text)
        if verdict == "safety":
            await self._safety_stop()
        elif verdict == "farewell":
            self._pending_end = "farewell"

    def _on_reply_done(self) -> None:
        text = " ".join(self._reply_text).strip()
        self._reply_open, self._reply_text = False, []
        latency, self._reply_latency = self._reply_latency, None
        self._later(lambda: self._after_reply(text, latency))

    async def _after_reply(self, text: str, latency: int | None) -> None:
        if self._fixed and text:
            self._fixed.popleft()          # the reply to a line we gave it: already recorded exactly
        elif text:
            await self.session.record_reply(text, latency)
        if self._closing or not text:
            return
        st = self.session.state
        if st.escalated:
            await self._finish("handoff")
        elif st.end_requested:
            await self._finish("end_call")
        elif self._pending_end:
            await self._finish(self._pending_end)
        else:
            trigger = self.session.post_turn_trigger()
            if trigger:
                self._closing = True
                handoff = (self.session.config.get("policy") or {}).get("handoff_message") or "I'm connecting you with a specialist."
                await self.session.announce(handoff, {"handoff": True})
                await self.session.escalate(*trigger)
                await self._instruct(handoff)
                await self._finish("handoff")

    async def _on_usage(self, frame: MetricsFrame) -> None:
        for item in frame.data or []:
            value = getattr(item, "value", None)
            if value is None or not hasattr(value, "prompt_tokens"):
                continue
            prompt, completion = int(value.prompt_tokens or 0), int(value.completion_tokens or 0)
            in_audio = int(getattr(value, "input_audio_tokens", 0) or 0)
            out_audio = int(getattr(value, "output_audio_tokens", 0) or 0)
            if not self.prices:
                log.warning("no price for the speech model; cost counted as 0")
            self.session.add_usage(prompt, completion, usage_cost(self.prices, prompt, completion, in_audio, out_audio))

    def on_bot_started(self) -> None:
        self._bot_speaking = True
        if not self._reminder_pending:
            self._silent_since = None
        if self.controls.welcoming:
            self._welcome_spoken = True
            if self._welcome_end:
                self._welcome_end.cancel()
                self._welcome_end = None

    async def on_bot_stopped(self) -> None:
        self._bot_speaking = False
        self._bot_stopped.set()
        if self._reminder_pending:
            self._reminder_pending = False
        else:
            self._silent_since = time.monotonic()
            self._reminded = False
        if self.controls.welcoming and self._welcome_spoken and not self._welcome_end:
            self._welcome_end = asyncio.get_running_loop().call_later(self.WELCOME_GRACE_S, self._end_welcome)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            self._silent_since = None
            self._reminded = False
            self._reminder_pending = False
        elif isinstance(frame, (UserStoppedSpeakingFrame, ProposedUserStoppedSpeakingFrame)):
            self._user_stopped_at = time.monotonic()  # the model's own end-of-turn, for latency_ms (RB-08)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._reply_open = True
        elif isinstance(frame, TTSTextFrame):
            if self._reply_open:
                self._reply_text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._reply_open:
                self._on_reply_done()
        elif isinstance(frame, InterruptionFrame):
            if self._reply_open:  # a partial reply is still recorded, marked as cut off
                text = " ".join(self._reply_text).strip()
                self._reply_open, self._reply_text = False, []
                if text and not self._fixed:
                    self._later(lambda: self.session.record_reply(text + " [interrupted]", None))
        elif isinstance(frame, MetricsFrame):
            self._later(lambda: self._on_usage(frame))
        elif isinstance(frame, TTSAudioRawFrame):
            if self._user_stopped_at is not None and self._reply_latency is None:  # first audio of the reply (RB-08)
                self._reply_latency = int((time.monotonic() - self._user_stopped_at) * 1000)
                self._user_stopped_at = None
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.on_bot_stopped()
        elif isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._end_welcome()
            self._stop_clocks()
            if isinstance(frame, EndFrame):
                await self.drain()         # a call that ends normally keeps its last records
            self._stop_worker()
            if self._end_timer:
                self._end_timer.cancel()
                self._end_timer = None
        await self.push_frame(frame, direction)


# ---------------------------------------------------------------- building the pieces
@dataclass
class RealtimePieces:
    service: Any
    user_aggregator: Any
    assistant_aggregator: Any
    gate: RealtimeGate
    tap: RealtimeTap
    brain: RealtimeBrain


def build_realtime(
    session: AgentSession, controls: LiveControls, on_end: Callable[[str], Awaitable[None]], deepgram_key: str = "",
    base_url: str | None = None,
) -> RealtimePieces:
    """Construct the service, aggregators, gate and brain for one call without opening a connection (VO-06)."""
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

    model = speech_model()
    voice = get_settings().realtime_voice
    props = session_properties(session, controls.turn, voice)
    service = OpenAIRealtimeLLMService(
        api_key=model.api_key,
        **({"base_url": base_url} if base_url else {}),   # tests point it at a fake server
        settings=OpenAIRealtimeLLMService.Settings(model=model.model, session_properties=props),
    )

    async def handler(params: Any) -> None:
        out = await session.run_tool(params.tool_call_id, params.function_name, json.dumps(params.arguments or {}))
        if session.state.escalated or session.state.end_requested:
            brain.arm_ending()
        await brain.deliver_tool_result(params.tool_call_id, out, params)

    for schema in session.tool_schemas():
        service.register_function(schema["function"]["name"], handler, cancel_on_interruption=False)

    context = LLMContext(messages=[], tools=props.tools)
    aggregators = LLMContextAggregatorPair(context)
    brain = RealtimeBrain(session, on_end, controls, service, voice=voice, prices=model.prices, deepgram_key=deepgram_key)
    gate = RealtimeGate(controls)
    brain.gate = gate
    tap = RealtimeTap(brain)

    async def refresh() -> None:
        """Push the current instructions and turn detection to the live session (RB-07, RB-10)."""
        fresh = session_properties(session, controls.turn, voice)
        await service.queue_frame(LLMUpdateSettingsFrame(
            delta=OpenAIRealtimeLLMService.Settings(session_properties=fresh)))

    brain.refresh_session = refresh
    controls.on_voice = lambda _voice, _speed: refresh()   # a persona switch changes the style, never the voice (RB-10)
    controls.on_turn = refresh                              # a live turn-detection change (RB-07)
    return RealtimePieces(service, aggregators.user(), aggregators.assistant(), gate, tap, brain)
