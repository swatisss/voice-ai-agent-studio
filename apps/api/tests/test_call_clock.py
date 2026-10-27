"""The silence and call-length clock shared by the cascade and realtime pipelines, driven with fake times.

Covers: CE-04, CE-05, RV-11
"""
from __future__ import annotations

from voiceai.runtime import endings
from voiceai.runtime.call_clock import CLOSE_IDLE, CLOSE_MAX, REMIND, CallClock

POLICY = {"silence_reminder_s": 10, "silence_end_s": 30, "max_call_seconds": 600}


def waiting_clock(at: float = 100.0) -> CallClock:
    clock = CallClock(POLICY, started=0.0)
    clock.wait_for_caller(at)
    return clock


def test_reminder_once_then_idle_close():
    """Covers: CE-04"""
    clock = waiting_clock()
    assert clock.tick(105, quiet=True) is None
    assert clock.tick(111, quiet=True) is REMIND and REMIND.line == endings.REMINDER_LINE
    clock.agent_started()                  # the reminder plays ...
    clock.agent_finished(113)              # ... and keeps the silence's original start
    assert clock.silent_since == 100
    assert clock.tick(115, quiet=True) is None
    assert clock.tick(131, quiet=True) is CLOSE_IDLE and CLOSE_IDLE.reason == "idle"


def test_caller_speech_resets_and_the_next_agent_line_starts_a_fresh_silence():
    """Covers: CE-04"""
    clock = waiting_clock()
    assert clock.tick(111, quiet=True) is REMIND
    clock.caller_started()
    assert clock.silent_since is None and clock.tick(400, quiet=True) is None
    clock.agent_started()
    clock.agent_finished(410)
    assert clock.silent_since == 410 and not clock.reminded


def test_nobody_is_silent_while_something_plays():
    """Covers: CE-04, RV-11"""
    assert waiting_clock().tick(500, quiet=False) is None


def test_finishing_while_not_waiting_keeps_the_clock_stopped():
    """Covers: RV-11 (the realtime bridge: audio stopped but a reply is still active)"""
    clock = CallClock(POLICY, started=0.0)
    clock.agent_finished(100, waiting=False)
    assert clock.silent_since is None


def test_maximum_length_wins_over_everything():
    """Covers: CE-05"""
    clock = CallClock({"max_call_seconds": 60}, started=1000.0)
    assert clock.tick(1059, quiet=False) is None
    assert clock.tick(1061, quiet=False) is CLOSE_MAX and CLOSE_MAX.line == endings.MAX_DURATION_LINE


def test_defaults_without_a_policy():
    clock = CallClock(None, started=0.0)
    assert (clock.reminder_s, clock.end_s, clock.max_call_s) == (10.0, 30.0, 600.0)
