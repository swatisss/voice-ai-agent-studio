"""Turn aggregation and the brain processor that bridges Pipecat to AgentSession.

Spec: /architecture/voice-pipeline.md (Pipeline processors), /decisions/adr-0002-voice-pipeline.md
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

from voiceai.runtime.session import AgentSession

log = logging.getLogger("voiceai.voice")


class UserTurnFrame(Frame):
    """One complete caller turn (our own frame type)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class TurnAggregator(FrameProcessor):
    """Collects final transcripts into one caller turn; dispatches after a short silence (VO-02)."""

    def __init__(self, delay_ms: int = 350, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.delay = delay_ms / 1000
        self.buffer: list[str] = []
        self.speaking = False
        self._timer: asyncio.Task[None] | None = None

    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    def _start_timer(self) -> None:
        self._cancel_timer()
        self._timer = asyncio.create_task(self._fire_later())

    async def _fire_later(self) -> None:
        await asyncio.sleep(self.delay)
        await self.flush()

    async def flush(self) -> None:
        text = " ".join(t.strip() for t in self.buffer if t.strip())
        self.buffer = []
        if text:
            await self.push_frame(UserTurnFrame(text))

    async def handle(self, frame: Frame) -> bool:
        """Update turn state for one frame; returns True if the frame is consumed here."""
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self.speaking = True
            self._cancel_timer()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.speaking = False
            self._start_timer()
        elif isinstance(frame, TranscriptionFrame):
            self.buffer.append(frame.text)
            if not self.speaking:
                self._start_timer()
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
    """Runs AgentSession for each caller turn and streams the reply to TTS."""

    def __init__(self, session: AgentSession, on_end: Callable[[str], Awaitable[None]], **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.session = session
        self.on_end = on_end
        self._task: asyncio.Task[None] | None = None
        self._bot_speaking = False
        self._greeted = False
        self._bot_stopped = asyncio.Event()

    async def greet(self) -> None:
        if self._greeted:
            return
        self._greeted = True
        await self.push_frame(OutputTransportMessageUrgentFrame(message={"type": "ready"}))
        greeting = await self.session.start()
        await self._speak_text([greeting])

    async def _speak_text(self, chunks: list[str]) -> None:
        await self.push_frame(LLMFullResponseStartFrame())
        for c in chunks:
            await self.push_frame(LLMTextFrame(c))
        await self.push_frame(LLMFullResponseEndFrame())

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

    async def _finish(self, reason: str) -> None:
        # let the goodbye play out before closing (max 10 s)
        self._bot_stopped.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._bot_stopped.wait(), 10)
        await self.on_end(reason)

    async def _cancel_task(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, UserTurnFrame):
            await self._cancel_task()
            self._task = asyncio.create_task(self._respond(frame.text))
            return
        if isinstance(frame, VADUserStartedSpeakingFrame):  # VO-03 barge-in
            if self._bot_speaking or (self._task and not self._task.done()):
                await self._cancel_task()
                await self.broadcast_interruption()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._bot_stopped.set()
        elif isinstance(frame, InputTransportMessageFrame):
            if isinstance(frame.message, dict) and frame.message.get("type") == "hangup":
                await self._cancel_task()
                await self.on_end("hangup")
            return
        elif isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._cancel_task()
        elif isinstance(frame, InterruptionFrame):
            pass
        await self.push_frame(frame, direction)
