"""The call floor: who may speak on a voice call, and when it ends. Shared by both voice pipelines.

Spec: /architecture/voice-pipeline.md (BrainProcessor welcome), /architecture/realtime-voice.md (RV-07, RV-11),
/architecture/call-ending-and-feedback.md (CE-04, CE-05, CE-06)

Pipecat-free. A pipeline reports what happened (agent audio started or stopped, a reply started or settled, the caller
started talking) and the floor owns the rules around it: the protected welcome (VO-08), the silence and call-length
clock, the closing state that nothing may interrupt, and ending the call once, after the last line has played. What
differs per pipeline sits behind `Stage`: how a fixed line is spoken and how to wait for the audio to drain.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from voiceai.runtime.call_clock import CallClock


class Stage(Protocol):
    """What the floor needs from a voice pipeline."""

    def working(self) -> bool: ...                  # a reply or a tool call is in progress
    async def say(self, text: str) -> None: ...      # speak a fixed line verbatim
    async def drained(self) -> None: ...             # returns once the last line has played (bounded wait)
    async def guard_changed(self) -> None: ...       # welcome or closing protection was switched on or off


class CallFloor:
    WELCOME_GRACE_S = 0.8        # silence after the welcome audio before the protection ends (bridges gaps between sentences)
    WELCOME_MIN_TIMEOUT_S = 15.0  # safety net if the welcome never finishes speaking
    WELCOME_SLOW_CHARS_PER_S = 6.0
    RUN_WATCHDOG = True
    WATCHDOG_TICK_S = 0.5

    def __init__(
        self, session: Any, controls: Any, stage: Stage, on_end: Callable[[str], Awaitable[None]],  # noqa: ANN401
    ) -> None:
        self.session = session
        self.controls = controls     # `controls.welcoming` is read by the cascade's TurnAggregator
        self.stage = stage
        self.on_end = on_end
        self.clock = CallClock(self._policy(), time.monotonic())
        self.bot_speaking = False
        self.closing = False         # the call is ending: nothing may interrupt or restart it
        self.ended = False
        self._greeted = False
        self._welcome_spoken = False
        self._welcome_produced = False
        self._welcome_end: asyncio.TimerHandle | None = None
        self._welcome_timeout: asyncio.TimerHandle | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    def _policy(self) -> dict[str, Any] | None:
        return (getattr(self.session, "config", None) or {}).get("policy")

    # ------------------------------------------------------------ state
    @property
    def welcoming(self) -> bool:
        return self.controls.welcoming

    @welcoming.setter
    def welcoming(self, value: bool) -> None:
        self.controls.welcoming = value

    @property
    def busy(self) -> bool:
        return self.bot_speaking or self.stage.working()

    @property
    def listening(self) -> bool:
        """Caller speech counts as a turn (not while the welcome plays or the call is closing, VO-08 and CE-06)."""
        return not (self.closing or self.welcoming)

    def may_interrupt(self, allow_interruptions: bool) -> bool:
        """VO-03 barge-in is possible: never during the welcome or the closing line, and only if the agent allows it."""
        return self.listening and allow_interruptions

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """The call is live: restart the clock and, unless disabled, tick it in the background."""
        self.clock = CallClock(self._policy(), time.monotonic())
        if self.RUN_WATCHDOG and self._watchdog is None:
            self._watchdog = asyncio.get_running_loop().create_task(self._watch())

    async def welcome(self, opening: Callable[[], Awaitable[str]]) -> None:
        """Speak the welcome once (VO-07, RV-07), protected from the first moment until its audio has played."""
        if self._greeted:
            return
        self._greeted = True
        self.welcoming = True  # noise can arrive before any audio is out
        try:
            await self.stage.guard_changed()
            greeting = await opening()
            timeout = max(self.WELCOME_MIN_TIMEOUT_S, len(greeting) / self.WELCOME_SLOW_CHARS_PER_S)
            self._welcome_timeout = asyncio.get_running_loop().call_later(timeout, self._later_end_welcome)
            await self.stage.say(greeting)
        except BaseException:
            await self._end_welcome()
            raise

    def welcome_produced(self) -> None:
        """All of the welcome has been handed to speech output: the protection may end once its audio stops."""
        self._welcome_produced = True
        if self.welcoming and self._welcome_spoken and not self.bot_speaking:
            self._arm_welcome_end()

    async def stop(self) -> None:
        """The pipeline is shutting down: cancel timers and background work."""
        self.closing = True
        self.welcoming = False
        self._cancel_welcome_timers()
        for task in (self._watchdog, *self._tasks):
            if task and not task.done() and task is not asyncio.current_task():
                task.cancel()
        self._watchdog = None

    async def settle(self) -> None:
        """Wait for background work (endings, timers' callbacks) started so far; used by tests."""
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------ facts from the pipeline
    def bot_started(self) -> None:
        self.bot_speaking = True
        self.clock.agent_started()
        if self.welcoming:
            self._welcome_spoken = True
            if self._welcome_end:  # audio resumed after a gap between sentences
                self._welcome_end.cancel()
                self._welcome_end = None

    def bot_stopped(self, waiting: bool = True) -> None:
        """The agent's audio stopped; `waiting` is false when more of the agent's reply is still on its way."""
        self.bot_speaking = False
        self.clock.agent_finished(time.monotonic(), waiting=waiting)
        if self.welcoming and self._welcome_spoken and self._welcome_produced and not self._welcome_end:
            self._arm_welcome_end()

    def reply_started(self) -> None:
        """The agent began producing a reply (before any audio)."""
        self.clock.agent_started()

    def caller_started(self) -> None:
        self.clock.caller_started()

    def settled(self) -> None:
        """A reply finished without leaving audio playing: the caller is expected to speak now."""
        if not self.bot_speaking and not self.welcoming:
            self.clock.wait_for_caller(time.monotonic())

    # ------------------------------------------------------------ clocks (CE-04, CE-05, RV-11)
    async def _watch(self) -> None:
        while not self.closing:
            await asyncio.sleep(self.WATCHDOG_TICK_S)
            await self.tick()

    async def tick(self, now: float | None = None) -> None:
        """One tick of the silence and call-length clock (called directly by tests with a fake `now`)."""
        if self.closing:
            return
        action = self.clock.tick(time.monotonic() if now is None else now, quiet=not (self.welcoming or self.busy))
        if action is None:
            return
        if action.kind == "close":
            await self.close_with(action.line, action.reason or "idle")
        else:
            await self.stage.say(await self.session.announce(action.line, {"silence_reminder": True}))

    # ------------------------------------------------------------ ending (CE-06)
    async def begin_closing(self, tell_stage: bool = True) -> None:
        """Nothing may interrupt or start a reply once the call is closing."""
        if self.closing:
            return
        self.closing = True
        if tell_stage:
            await self.stage.guard_changed()

    async def close_with(self, line: str, reason: str) -> None:
        """Say a closing line, then end the call once it has played."""
        await self.begin_closing()
        await self.stage.say(await self.session.announce(line, {"closing": reason}))
        self.finish_after_drain(reason)

    def finish_after_drain(self, reason: str) -> asyncio.Task[None]:
        """End the call once the last line has played. Runs in the background: draining waits on pipeline events."""
        return self._spawn(self._finish(reason))

    async def _finish(self, reason: str) -> None:
        await self.begin_closing()
        await self.stage.drained()
        await self.end(reason)

    async def end(self, reason: str) -> None:
        """End the call now, once: later calls (a hang-up racing a goodbye) are ignored."""
        if self.ended:
            return
        self.ended = True
        self.closing = True
        await self.on_end(reason)

    # ------------------------------------------------------------ welcome protection (VO-08)
    def _arm_welcome_end(self) -> None:
        self._welcome_end = asyncio.get_running_loop().call_later(self.WELCOME_GRACE_S, self._later_end_welcome)

    def _later_end_welcome(self) -> None:
        self._spawn(self._end_welcome())

    def _cancel_welcome_timers(self) -> None:
        for handle in (self._welcome_end, self._welcome_timeout):
            if handle:
                handle.cancel()
        self._welcome_end = self._welcome_timeout = None

    async def _end_welcome(self) -> None:
        if not self.welcoming:
            return
        self.welcoming = False
        self._welcome_spoken = False
        self._cancel_welcome_timers()
        if not self.closing:
            await self.stage.guard_changed()  # the agent's own turn detection applies from here on
        if not self.busy:  # the caller gets a full silence window after the welcome
            self.clock.wait_for_caller(time.monotonic())

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
