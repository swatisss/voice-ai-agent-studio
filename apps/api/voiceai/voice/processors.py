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
from voiceai.runtime.call_floor import CallFloor
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
        last_agent_text: Callable[[], str | None] | None = None, vad_stop_ms: int = VAD_STOP_MS,
        welcoming: Callable[[], bool] | None = None, **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(**kwargs)
        self.controls = controls
        self.welcoming = welcoming or (lambda: False)  # the call floor's welcome protection (VO-08)
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
            if self.welcoming():  # VO-08: speech heard during the welcome is never a caller turn
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

    The call floor owns the protected welcome (VO-08), the silence and call-length clock and the closing state; this
    processor maps Pipecat frames onto it and is its `Stage`: fixed lines go to TTS like any reply.
    """

    FINISH_WAIT_S = 10.0  # the most a goodbye may take to play out before the call closes

    def __init__(
        self, session: AgentSession, on_end: Callable[[str], Awaitable[None]], controls: LiveControls, **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.controls = controls
        self.floor = CallFloor(session, self, on_end)
        self._task: asyncio.Task[None] | None = None
        self._greeted = False
        self._held: list[str] = []
        self._bot_stopped = asyncio.Event()

    async def greet(self) -> None:
        async def opening() -> str:
            await self.push_frame(OutputTransportMessageUrgentFrame(message={"type": "ready"}))
            return await self.session.start()

        if self._greeted:
            return
        self._greeted = True
        self.floor.start()
        await self.floor.welcome(opening)
        self.floor.welcome_produced()  # the whole welcome is with TTS now

    # -- the floor's Stage
    def working(self) -> bool:
        return bool(self._task and not self._task.done())

    async def say(self, text: str) -> None:
        await self._speak_text([text])

    async def drained(self) -> None:
        # let the goodbye play out before closing
        self._bot_stopped.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._bot_stopped.wait(), self.FINISH_WAIT_S)

    async def guard_changed(self) -> None:
        pass  # the cascade reads the floor at every decision

    async def _speak_text(self, chunks: list[str]) -> None:
        await self.push_frame(LLMFullResponseStartFrame())
        for c in chunks:
            await self.push_frame(LLMTextFrame(c))
        await self.push_frame(LLMFullResponseEndFrame())

    # -- decisions (also called directly by tests)
    async def on_bot_stopped(self) -> None:
        self.floor.bot_stopped()
        self._bot_stopped.set()
        await self._release_held()

    async def on_user_started(self) -> None:
        """VO-03 barge-in, unless interruptions are disabled (TD-07), the welcome is playing (VO-08) or the call is closing."""
        self.floor.caller_started()
        if self.floor.may_interrupt(self.controls.turn.allow_interruptions) and self.floor.busy:
            await self._cancel_task()
            await self.broadcast_interruption()

    async def on_user_turn(self, text: str) -> None:
        if not self.floor.listening:  # VO-08: heard during the welcome (often our own echo), or the call is closing
            log.debug("dropping caller turn heard during the welcome or closing: %r", text)
            return
        if self.floor.busy and not self.controls.turn.allow_interruptions:
            self._held.append(text)  # answered after the agent finishes
            return
        await self._cancel_task()
        self._task = asyncio.create_task(self._respond(text))

    async def _release_held(self) -> None:
        if self._held and not self.floor.busy:
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
        if self.session.state.ended:  # the runtime ended the call: goodbye, farewell or hand-off (CE-01, CE-02)
            self.floor.finish_after_drain(getattr(self.session, "end_reason", None) or "end_call")
        else:
            self.floor.settled()  # a reply with no speech still leaves the caller waiting
            if not self.floor.bot_speaking:
                asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self._release_held()))

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
            self.floor.bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.on_bot_stopped()
        elif isinstance(frame, InputTransportMessageFrame):
            if isinstance(frame.message, dict) and frame.message.get("type") == "hangup":
                await self._cancel_task()
                await self.floor.end("hangup")
            return
        elif isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self.floor.stop()
            await self._cancel_task()
        elif isinstance(frame, InterruptionFrame):
            pass
        await self.push_frame(frame, direction)
