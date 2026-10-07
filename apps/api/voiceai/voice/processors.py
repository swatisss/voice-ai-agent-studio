"""Turn aggregation and the brain processor that bridges Pipecat to AgentSession.

Spec: /architecture/voice-pipeline.md (Pipeline processors), /architecture/turn-detection.md
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputTransportMessageFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai.live import LiveControls
from voiceai.runtime.session import AgentSession
from voiceai.voice.turn_detection import VAD_STOP_MS, TurnEvaluator

log = logging.getLogger("voiceai.voice")


class UserTurnFrame(Frame):
    """One complete caller turn (our own frame type)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class TurnAggregator(FrameProcessor):
    """Collects final transcripts into one caller turn and decides when it is over (TD-01..TD-06).

    Settings are read from `controls.turn` at every decision, so live changes apply immediately.
    """

    def __init__(
        self, controls: LiveControls, evaluator: TurnEvaluator | None = None,
        last_agent_text: Callable[[], str | None] | None = None, vad_stop_ms: int = VAD_STOP_MS, **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(**kwargs)
        self.controls = controls
        self.evaluator = evaluator or TurnEvaluator()
        self.last_agent_text = last_agent_text or (lambda: None)
        self.vad_stop_ms = vad_stop_ms
        self.buffer: list[str] = []
        self.speaking = False
        self._timer: asyncio.Task[None] | None = None

    # -- timers
    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done() and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None

    def _schedule(self, seconds: float, stage: str) -> None:
        self._cancel_timer()
        self._timer = asyncio.create_task(self._fire(seconds, stage))

    async def _fire(self, seconds: float, stage: str) -> None:
        await asyncio.sleep(seconds)
        await self.decide(stage)

    # -- decisions
    async def decide(self, stage: str) -> None:
        """Timer 1 ("first") may extend the wait in semantic mode; timer 2 ("extra") always dispatches."""
        text = " ".join(t.strip() for t in self.buffer if t.strip())
        if not text:
            return
        turn = self.controls.turn
        if turn.mode != "semantic" or stage == "extra":
            await self.flush()
            return
        verdict = await self.evaluator.is_complete(text, self.last_agent_text(), turn)
        log.debug("turn verdict complete=%s (%s/%s) text=%r", verdict.complete, verdict.source, verdict.reason, text)
        if verdict.complete or turn.max_extra_wait_ms <= 0:
            await self.flush()
        else:
            self._schedule(turn.max_extra_wait_ms / 1000, "extra")

    async def flush(self) -> None:
        text = " ".join(t.strip() for t in self.buffer if t.strip())
        self.buffer = []
        if text:
            await self.push_frame(UserTurnFrame(text))

    # -- frame handling
    async def handle(self, frame: Frame) -> bool:
        """Update turn state for one frame; returns True if the frame is consumed here."""
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self.speaking = True
            self._cancel_timer()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.speaking = False
            self._schedule(self.controls.turn.first_delay_s(self.vad_stop_ms), "first")
        elif isinstance(frame, TranscriptionFrame):
            if self.controls.welcoming:  # VO-08: speech heard during the welcome is never a caller turn
                return True
            self.buffer.append(frame.text)
            if not self.speaking:
                self._schedule(self.controls.turn.first_delay_s(self.vad_stop_ms), "first")
            return True
        elif isinstance(frame, InterimTranscriptionFrame):
            return True
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._cancel_timer()
        return False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if not await self.handle(frame):
            await self.push_frame(frame, direction)


class BrainProcessor(FrameProcessor):
    """Runs AgentSession for each caller turn and streams the reply to TTS.

    The opening welcome is protected (VO-08): while it plays, caller speech (or the agent's own voice
    leaking from the speakers into the microphone) neither interrupts it nor is answered.
    """

    WELCOME_GRACE_S = 0.8        # silence after the welcome audio before the protection ends (bridges gaps between sentences)
    WELCOME_MIN_TIMEOUT_S = 15.0  # safety net if the welcome never finishes speaking
    WELCOME_SLOW_CHARS_PER_S = 6.0

    # class-level defaults so the welcome state exists even on test doubles that skip __init__
    _welcome_spoken = False
    _welcome_end: asyncio.TimerHandle | None = None
    _welcome_timeout: asyncio.TimerHandle | None = None

    @property
    def _welcoming(self) -> bool:
        return self.controls.welcoming  # shared with the TurnAggregator, which drops transcripts meanwhile

    @_welcoming.setter
    def _welcoming(self, value: bool) -> None:
        self.controls.welcoming = value

    def __init__(
        self, session: AgentSession, on_end: Callable[[str], Awaitable[None]], controls: LiveControls, **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.on_end = on_end
        self.controls = controls
        self._task: asyncio.Task[None] | None = None
        self._bot_speaking = False
        self._greeted = False
        self._held: list[str] = []
        self._bot_stopped = asyncio.Event()

    async def greet(self) -> None:
        if self._greeted:
            return
        self._greeted = True
        self._welcoming = True  # protected from the first moment: noise can arrive before any audio is out
        try:
            await self.push_frame(OutputTransportMessageUrgentFrame(message={"type": "ready"}))
            greeting = await self.session.start()
            loop = asyncio.get_running_loop()
            timeout = max(self.WELCOME_MIN_TIMEOUT_S, len(greeting) / self.WELCOME_SLOW_CHARS_PER_S)
            self._welcome_timeout = loop.call_later(timeout, self._end_welcome)
            await self._speak_text([greeting])
        except BaseException:
            self._end_welcome()
            raise

    def _end_welcome(self) -> None:
        self._welcoming = False
        self._welcome_spoken = False
        for handle in (self._welcome_end, self._welcome_timeout):
            if handle:
                handle.cancel()
        self._welcome_end = self._welcome_timeout = None

    def on_bot_started(self) -> None:
        self._bot_speaking = True
        if self._welcoming:
            self._welcome_spoken = True
            if self._welcome_end:  # audio resumed after a gap between sentences
                self._welcome_end.cancel()
                self._welcome_end = None

    async def on_bot_stopped(self) -> None:
        self._bot_speaking = False
        self._bot_stopped.set()
        if self._welcoming and self._welcome_spoken and not self._welcome_end:
            self._welcome_end = asyncio.get_running_loop().call_later(self.WELCOME_GRACE_S, self._end_welcome)
        await self._release_held()

    async def _speak_text(self, chunks: list[str]) -> None:
        await self.push_frame(LLMFullResponseStartFrame())
        for c in chunks:
            await self.push_frame(LLMTextFrame(c))
        await self.push_frame(LLMFullResponseEndFrame())

    @property
    def busy(self) -> bool:
        return self._bot_speaking or bool(self._task and not self._task.done())

    # -- decisions (also called directly by tests)
    async def on_user_started(self) -> None:
        """VO-03 barge-in, unless interruptions are disabled (TD-07) or the welcome is playing (VO-08)."""
        if self._welcoming or not self.controls.turn.allow_interruptions:
            return
        if self.busy:
            await self._cancel_task()
            await self.broadcast_interruption()

    async def on_user_turn(self, text: str) -> None:
        if self._welcoming:  # VO-08: heard during the welcome (often our own echo): not a caller turn
            log.debug("dropping caller turn heard during the welcome: %r", text)
            return
        if self.busy and not self.controls.turn.allow_interruptions:
            self._held.append(text)  # answered after the agent finishes
            return
        await self._cancel_task()
        self._task = asyncio.create_task(self._respond(text))

    async def _release_held(self) -> None:
        if self._held and not self.busy:
            text, self._held = " ".join(self._held), []
            self._task = asyncio.create_task(self._respond(text))

    async def _respond(self, text: str) -> None:
        started = False
        try:
            async for chunk in self.session.respond(text):
                if not started:
                    await self.push_frame(LLMFullResponseStartFrame())
                    started = True
                await self.push_frame(LLMTextFrame(chunk if chunk.endswith(" ") else chunk + " "))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("brain turn failed")
        finally:
            if started:
                await self.push_frame(LLMFullResponseEndFrame())
        if self.session.state.ended:
            await self._finish("end_call")
        elif not self._bot_speaking:
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self._release_held()))

    async def _finish(self, reason: str) -> None:
        # let the goodbye play out before closing (max 10 s)
        self._bot_stopped.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._bot_stopped.wait(), 10)
        await self.on_end(reason)

    async def _cancel_task(self) -> None:
        if self._task and not self._task.done() and self._task is not asyncio.current_task():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, UserTurnFrame):
            await self.on_user_turn(frame.text)
            return
        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self.on_user_started()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.on_bot_stopped()
        elif isinstance(frame, InputTransportMessageFrame):
            if isinstance(frame.message, dict) and frame.message.get("type") == "hangup":
                await self._cancel_task()
                await self.on_end("hangup")
            return
        elif isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._end_welcome()
            await self._cancel_task()
        elif isinstance(frame, InterruptionFrame):
            pass
        await self.push_frame(frame, direction)
