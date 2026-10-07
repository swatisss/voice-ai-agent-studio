"""Turn detection: heuristic, aggregator timing, LLM fallback, live changes, interruptions, validation.

Covers: TD-01, TD-02, TD-03, TD-04, TD-05, TD-06, TD-07, TD-08, VO-02
"""
from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame

from voiceai.live import LiveControls
from voiceai.voice.processors import BrainProcessor, TurnAggregator, UserTurnFrame
from voiceai.voice.turn_detection import TurnEvaluator, TurnSettings, expected_slots, heuristic_verdict

H = {"X-Tenant-Id": "evergreen-members"}


def make_aggregator(**turn):  # noqa: ANN003, ANN202
    controls = LiveControls(turn=TurnSettings(**turn))
    agg = TurnAggregator(controls, last_agent_text=lambda: agg.agent_said)
    agg.agent_said = None
    agg.turns = []

    async def capture(frame, direction=None):  # noqa: ANN001, ANN202
        if isinstance(frame, UserTurnFrame):
            agg.turns.append(frame.text)

    agg.push_frame = capture  # type: ignore[method-assign]
    return agg, controls


def say(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text, "u", "t")


async def caller_pauses(agg: TurnAggregator, text: str) -> None:
    """The caller speaks `text`, then stops (VAD stop, then the final transcript)."""
    await agg.handle(VADUserStartedSpeakingFrame())
    await agg.handle(VADUserStoppedSpeakingFrame())
    await agg.handle(say(text))


# silence thresholds in these tests are tiny (50 ms first stage via min_silence 250) to keep them fast
FAST = dict(min_silence_ms=250, max_extra_wait_ms=400)


async def test_normal_mode_merges_and_dispatches_once():
    """Covers: TD-01, VO-02"""
    agg, _ = make_aggregator(mode="vad", **FAST)
    await agg.handle(VADUserStartedSpeakingFrame())
    await agg.handle(say("My claim is"))
    await agg.handle(VADUserStoppedSpeakingFrame())
    await agg.handle(say("C-20931."))
    await asyncio.sleep(0.01)
    assert agg.turns == []  # still inside the silence window
    await asyncio.sleep(0.2)
    assert agg.turns == ["My claim is C-20931."]


async def test_semantic_waits_then_merges_continuation():
    """Covers: TD-02"""
    agg, _ = make_aggregator(mode="semantic", **FAST)
    await caller_pauses(agg, "I would like to check on my claim and")
    await asyncio.sleep(0.2)       # silence threshold passed ...
    assert agg.turns == []         # ... but the caller seems unfinished
    await agg.handle(VADUserStartedSpeakingFrame())  # continues within the extra window
    await agg.handle(VADUserStoppedSpeakingFrame())
    await agg.handle(say("it is C-20931."))
    await asyncio.sleep(0.2)
    assert agg.turns == ["I would like to check on my claim and it is C-20931."]


async def test_semantic_expected_digits_and_dob():
    """Covers: TD-03"""
    assert expected_slots("What's your member ID and date of birth?") == ["member_id", "date_of_birth"]
    ask_id = expected_slots("Can I have your member ID?")
    assert not heuristic_verdict("four eight two", ask_id).complete
    assert heuristic_verdict("four eight two nine one three", ask_id).complete
    assert heuristic_verdict("482913", ask_id).complete
    ask_both = ["member_id", "date_of_birth"]
    assert not heuristic_verdict("482913 April twelfth", ask_both).complete       # no year yet
    assert heuristic_verdict("482913, April twelfth 1986", ask_both).complete
    assert not heuristic_verdict("four eight two April twelve 1986", ask_both).complete  # DOB digits do not count toward the ID
    agg, _ = make_aggregator(mode="semantic", **FAST)
    agg.agent_said = "Can I have your member ID?"
    await caller_pauses(agg, "four eight two")
    await asyncio.sleep(0.2)
    assert agg.turns == []
    await agg.handle(say("nine one three"))
    await asyncio.sleep(0.2)
    assert agg.turns == ["four eight two nine one three"]


async def test_semantic_dispatches_after_extra_wait_or_immediately_when_zero():
    """Covers: TD-04"""
    agg, _ = make_aggregator(mode="semantic", min_silence_ms=250, max_extra_wait_ms=300)
    await caller_pauses(agg, "I need to check my")
    await asyncio.sleep(0.2)
    assert agg.turns == []
    await asyncio.sleep(0.4)
    assert agg.turns == ["I need to check my"]
    zero, _ = make_aggregator(mode="semantic", min_silence_ms=250, max_extra_wait_ms=0)
    await caller_pauses(zero, "I need to check my")
    await asyncio.sleep(0.2)
    assert zero.turns == ["I need to check my"]


async def test_llm_evaluator_falls_back_to_heuristic():
    """Covers: TD-05"""
    async def boom(last_agent, text):  # noqa: ANN001, ANN202
        raise RuntimeError("provider down")

    async def slow(last_agent, text):  # noqa: ANN001, ANN202
        await asyncio.sleep(5)
        return True

    llm = TurnSettings(mode="semantic", evaluator="llm")
    assert not (await TurnEvaluator(boom).is_complete("I would like to and", None, llm)).complete  # heuristic: ends on "and"
    assert (await TurnEvaluator(boom).is_complete("Check my claim please.", None, llm)).complete
    verdict = await TurnEvaluator(slow).is_complete("Check my claim please.", None, llm)  # times out
    assert verdict.complete and verdict.source == "heuristic"

    async def yes(last_agent, text):  # noqa: ANN001, ANN202
        return True

    assert (await TurnEvaluator(yes).is_complete("I need the", None, llm)).source == "llm"
    assert (await TurnEvaluator(yes).is_complete("I need the", None, TurnSettings(evaluator="heuristic"))).source == "heuristic"


async def test_live_mode_change_applies_to_next_decision():
    """Covers: TD-06"""
    agg, controls = make_aggregator(mode="vad", **FAST)
    await caller_pauses(agg, "I would like to check my claim and")
    await asyncio.sleep(0.2)
    assert agg.turns == ["I would like to check my claim and"]  # normal mode: dispatched at the silence threshold
    controls.turn = TurnSettings(mode="semantic", **FAST)       # changed live, same aggregator
    await caller_pauses(agg, "I would like to check my claim and")
    await asyncio.sleep(0.2)
    assert len(agg.turns) == 1                                   # semantic mode now holds the unfinished turn


class _Brain(BrainProcessor):
    def __init__(self, allow: bool) -> None:
        self.controls = LiveControls(turn=TurnSettings(allow_interruptions=allow))
        self._task = None
        self._bot_speaking = True
        self._held = []
        self.interrupted = 0
        self.cancelled = 0
        self.started: list[str] = []

    async def broadcast_interruption(self) -> None:  # type: ignore[override]
        self.interrupted += 1

    async def _cancel_task(self) -> None:
        self.cancelled += 1

    async def _respond(self, text: str) -> None:
        self.started.append(text)


async def test_interruptions_can_be_disabled():
    """Covers: TD-07"""
    off = _Brain(allow=False)
    await off.on_user_started()
    await off.on_user_turn("what about my claim")
    assert off.interrupted == 0 and off.cancelled == 0 and off.started == [] and off._held == ["what about my claim"]
    off._bot_speaking = False
    await off._release_held()
    await asyncio.sleep(0)
    assert off.started == ["what about my claim"]

    on = _Brain(allow=True)
    await on.on_user_started()
    assert on.interrupted == 1 and on.cancelled == 1
    await on.on_user_turn("hello")
    await asyncio.sleep(0)
    assert on.started == ["hello"]


async def test_turn_detection_bounds_are_validated(client, seeded):
    """Covers: TD-08"""
    agent_id = seeded["evergreen-members"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    for bad in ({"min_silence_ms": 100}, {"max_extra_wait_ms": 9000}, {"mode": "psychic"}, {"evaluator": "oracle"}):
        body = {**cfg, "voice": {"turn_detection": {**cfg["voice"]["turn_detection"], **bad}}}
        r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": body})
        assert r.status_code == 422, bad
    ok = {**cfg, "voice": {"turn_detection": {"mode": "semantic", "min_silence_ms": 900, "max_extra_wait_ms": 2000, "evaluator": "llm", "allow_interruptions": False}}}
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": ok})
    assert r.status_code == 200 and r.json()["draft_config"]["voice"]["turn_detection"]["evaluator"] == "llm"


def test_settings_roundtrip_ignores_unknown_keys():
    s = TurnSettings.from_dict({"mode": "semantic", "bogus": 1, "min_silence_ms": None})
    assert s.mode == "semantic" and s.min_silence_ms == 700
    assert s.first_delay_s() == pytest.approx(0.5)
