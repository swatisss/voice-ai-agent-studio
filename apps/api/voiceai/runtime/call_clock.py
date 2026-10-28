"""The silence and call-length clock shared by both voice pipelines.

Spec: /architecture/call-ending-and-feedback.md (CE-04, CE-05), /architecture/realtime-voice.md (RV-11)

Pure and Pipecat-free: the pipelines report what happened (the agent started or finished speaking, the caller
started speaking, the agent is waiting for the caller) and call `tick` with the current monotonic time; the clock
answers with what to do. Speaking the line and ending the call stay with the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from voiceai.runtime import endings
from voiceai.schemas import Policy

DEFAULT_REMINDER_S = float(Policy.model_fields["silence_reminder_s"].default)
DEFAULT_END_S = float(Policy.model_fields["silence_end_s"].default)
DEFAULT_MAX_CALL_S = float(Policy.model_fields["max_call_seconds"].default)


@dataclass(frozen=True)
class ClockAction:
    kind: Literal["remind", "close"]
    line: str
    reason: str | None = None  # end reason for `close`: `idle` or `max_duration`


REMIND = ClockAction("remind", endings.REMINDER_LINE)
CLOSE_IDLE = ClockAction("close", endings.IDLE_LINE, "idle")
CLOSE_MAX = ClockAction("close", endings.MAX_DURATION_LINE, "max_duration")


class CallClock:
    def __init__(self, policy: dict[str, Any] | None, started: float) -> None:
        policy = policy or {}
        self.reminder_s = float(policy.get("silence_reminder_s", DEFAULT_REMINDER_S))
        self.end_s = float(policy.get("silence_end_s", DEFAULT_END_S))
        self.max_call_s = float(policy.get("max_call_seconds", DEFAULT_MAX_CALL_S))
        self.started = started
        self.silent_since: float | None = None   # when the current silence began (None while someone is talking)
        self.reminded = False
        self._reminder_pending = False           # the reminder is being spoken: the silence keeps its original start

    def agent_started(self) -> None:
        """The agent began speaking or producing a reply: not silence (a reminder keeps the original start)."""
        if not self._reminder_pending:
            self.silent_since = None

    def agent_finished(self, now: float, waiting: bool = True) -> None:
        """The agent's audio stopped. After the reminder the silence goes on; otherwise, if the caller is now
        expected to answer (`waiting`), a fresh silence starts."""
        if self._reminder_pending:
            self._reminder_pending = False
        elif waiting:
            self.silent_since = now
            self.reminded = False

    def caller_started(self) -> None:
        """The caller is talking: the silence clock restarts after the next agent line (CE-04)."""
        self.silent_since = None
        self.reminded = False
        self._reminder_pending = False

    def wait_for_caller(self, now: float) -> None:
        """Nothing is playing and the caller is expected to speak (after the welcome, or a reply with no audio)."""
        if self.silent_since is None:
            self.silent_since = now

    def tick(self, now: float, quiet: bool) -> ClockAction | None:
        """One tick. `quiet` is false while the welcome, a reply or a tool is running: nobody is silent then."""
        if now - self.started >= self.max_call_s:
            return CLOSE_MAX  # CE-05
        if self.silent_since is None or not quiet:
            return None
        silent = now - self.silent_since
        if silent >= self.end_s:
            return CLOSE_IDLE  # CE-04
        if silent >= self.reminder_s and not self.reminded:
            self.reminded = True
            self._reminder_pending = True
            return REMIND
        return None
