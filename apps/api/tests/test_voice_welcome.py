"""The spoken welcome of a voice call: said once after `ready`, and protected from interruption and echo.

Spec: /architecture/voice-pipeline.md (BrainProcessor welcome), /api/voice-protocol.md
Covers: VO-07, VO-08
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)

from voiceai.modules.voice.controls import LiveControls
from voiceai.modules.voice.processors import BrainProcessor, TurnAggregator, UserTurnFrame
from voiceai.modules.voice.turn_detection import TurnSettings

WELCOME = "Thanks for calling Evergreen Health member services, this is Ava. I'm a virtual assistant."


class _Brain(BrainProcessor):
    """A BrainProcessor without a running pipeline: pushed frames, interruptions and replies are recorded."""

    def __init__(self, allow: bool = True, grace: float = 0.03) -> None:
        async def start() -> str:
            return WELCOME

        self.session = SimpleNamespace(start=start)
        self.controls = LiveControls(turn=TurnSettings(allow_interruptions=allow))
        self._task = None
        self._bot_speaking = False
        self._greeted = False
        self._held = []
        self._bot_stopped = asyncio.Event()
        self.WELCOME_GRACE_S = grace  # type: ignore[misc]
        self.pushed: list = []
        self.interrupted = 0
        self.replies: list[str] = []

    async def push_frame(self, frame, direction=None) -> None:  # type: ignore[override]  # noqa: ANN001
        self.pushed.append(frame)

    async def broadcast_interruption(self) -> None:  # type: ignore[override]
        self.interrupted += 1

    async def _respond(self, text: str) -> None:
        self.replies.append(text)


async def test_welcome_is_said_once_after_ready():
    """Covers: VO-07"""
    brain = _Brain()
    await brain.greet()
    await brain.greet()  # a repeated connect signal does not speak it again
    kinds = [type(f).__name__ for f in brain.pushed]
    assert kinds == ["OutputTransportMessageUrgentFrame", "LLMFullResponseStartFrame", "LLMTextFrame", "LLMFullResponseEndFrame"]
    ready, start, text, end = brain.pushed
    assert isinstance(ready, OutputTransportMessageUrgentFrame) and ready.message == {"type": "ready"}
    assert isinstance(start, LLMFullResponseStartFrame) and isinstance(end, LLMFullResponseEndFrame)
    assert isinstance(text, LLMTextFrame) and text.text == WELCOME
    brain._end_welcome()


async def test_welcome_is_not_interrupted_and_echo_is_not_answered():
    """Covers: VO-08"""
    brain = _Brain(allow=True)
    await brain.greet()
    brain.on_bot_started()  # the welcome is playing
    await brain.on_user_started()  # microphone picks up sound (an echo of the speakers, or the caller)
    await brain.on_user_turn("Thanks for calling Evergreen Health")  # what STT made of it
    assert brain.interrupted == 0
    assert brain.replies == [] and brain._held == []
    brain._end_welcome()


async def test_aggregator_ignores_speech_while_welcoming():
    """Covers: VO-08"""
    controls = LiveControls(turn=TurnSettings(min_silence_ms=250, max_extra_wait_ms=400))
    agg = TurnAggregator(controls)
    turns: list[str] = []

    async def capture(frame, direction=None) -> None:  # noqa: ANN001
        if isinstance(frame, UserTurnFrame):
            turns.append(frame.text)

    agg.push_frame = capture  # type: ignore[method-assign]
    controls.welcoming = True
    await agg.handle(VADUserStartedSpeakingFrame())
    await agg.handle(VADUserStoppedSpeakingFrame())
    assert await agg.handle(TranscriptionFrame("this is Ava", "u", "t")) is True  # consumed and dropped
    controls.welcoming = False
    await asyncio.sleep(0.5)
    assert turns == [] and agg.buffer == []  # nothing left over to fire as a turn after the welcome
    await agg.handle(TranscriptionFrame("what is my claim status", "u", "t"))
    await asyncio.sleep(0.5)
    assert turns == ["what is my claim status"]


async def test_protection_ends_after_the_audio_and_normal_rules_return():
    """Covers: VO-08, TD-07"""
    brain = _Brain(allow=True, grace=0.03)
    await brain.greet()
    brain.on_bot_started()
    await brain.on_bot_stopped()
    assert brain._welcoming  # still inside the grace period
    await asyncio.sleep(0.1)
    assert not brain._welcoming and not brain.controls.welcoming

    brain._bot_speaking = True  # the agent talks again; the caller speaks over it
    await brain.on_user_started()
    assert brain.interrupted == 1
    await brain.on_user_turn("what about my claim")
    await asyncio.sleep(0)
    assert brain.replies == ["what about my claim"]


async def test_gap_between_sentences_does_not_end_the_protection():
    """Covers: VO-08"""
    brain = _Brain(grace=0.05)
    await brain.greet()
    brain.on_bot_started()
    await brain.on_bot_stopped()  # the speech engine pauses between sentences ...
    await asyncio.sleep(0.02)
    brain.on_bot_started()        # ... and carries on within the grace period
    await asyncio.sleep(0.1)
    assert brain._welcoming
    await brain.on_bot_stopped()
    await asyncio.sleep(0.15)
    assert not brain._welcoming


async def test_protection_times_out_if_the_welcome_never_finishes():
    """Covers: VO-08"""
    brain = _Brain()
    brain.WELCOME_MIN_TIMEOUT_S = 0.05  # type: ignore[misc]
    brain.WELCOME_SLOW_CHARS_PER_S = 10_000.0  # type: ignore[misc]
    await brain.greet()  # the speech engine never reports audio
    assert brain._welcoming
    await asyncio.sleep(0.15)
    assert not brain._welcoming
    await brain.on_user_turn("hello?")
    await asyncio.sleep(0)
    assert brain.replies == ["hello?"]
