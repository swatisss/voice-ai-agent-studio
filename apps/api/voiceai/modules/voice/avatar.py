"""The agent's talking face: a Simli stage that can never make the agent harder to hear.

Spec: /architecture/avatar.md, /decisions/adr-0011-avatar-simli.md

Pipecat's `SimliVideoService` takes the agent's TTS audio and returns lip-synced video frames plus
the same speech re-timed to match them. On an avatar call it therefore *consumes* the TTS audio
and the caller hears the avatar's audio instead. That is the risk this module exists to contain: if
the vendor connection fails and the stage keeps consuming audio, the agent goes silent.

So the stage is wrapped in `PassThroughOnFailure`. It is a transparent processor until the session
is explicitly opened (the first participant joined), and again for good after any failure - the
agent's speech then reaches the caller unchanged and the call carries on (AV-05). A failed avatar
never ends a call.

Everything that touches the vendor SDK is imported lazily, so a deployment without the `simli`
extra, or with the avatar unconfigured, never loads it (AV-07).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    OutputImageRawFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai.core.config import get_settings

log = logging.getLogger("voiceai.voice")

OnFailure = Callable[[str], Awaitable[None]]

#: A vendor that hangs is a failure too. Without these limits an avatar that connects but never
#: answers would hold the welcome, or swallow the agent's speech, forever (AV-05).
OPEN_TIMEOUT_S = 15.0      # opening the vendor session
RETURN_TIMEOUT_S = 5.0     # speech sent to the vendor must come back, lip-synced, within this
MAX_PENDING_BYTES = 4_000_000
#: After the session opens, how long to wait for the vendor's first video frame before trusting it
#: anyway. A refusal (rate limit, bad face) shows up inside this window as an error or stop event,
#: and fails the stage before it has swallowed a word (AV-10).
READY_PROOF_S = 5.0

#: Avatars that hold, or are acquiring, a vendor session in this process (AV-11, AV-12).
_LIVE: set["PassThroughOnFailure"] = set()

#: The frames a rendering avatar consumes or acts on. When it is not rendering they are forwarded.
_RENDERED = (TTSAudioRawFrame, TTSStoppedFrame, InterruptionFrame, UserStartedSpeakingFrame)


def avatar_unavailable_reason() -> str | None:
    """Why there is no avatar on this deployment, or None when there is one (AV-01)."""
    s = get_settings()
    missing = [n for n, v in (("SIMLI_API_KEY", s.simli_api_key), ("SIMLI_FACE_ID", s.simli_face_id)) if not v]
    if missing:
        return f"{', '.join(missing)} not set in apps/api/.env (restart the API after editing it)"
    absent = [n for n in ("simli", "av") if importlib.util.find_spec(n) is None]
    if absent:
        return f"python package(s) {', '.join(absent)} not installed (run `uv sync` in apps/api)"
    return None


def avatar_available() -> bool:
    """Both Simli settings present and the SDK installed (AV-01).

    Anything less is not an error: the call is an ordinary video call with no face.
    """
    return avatar_unavailable_reason() is None


def scrub(text: str) -> str:
    """Remove the vendor key from anything about to be logged (AV-08).

    A vendor exception can echo a URL or header, so nothing from one is logged unscrubbed.
    """
    key = get_settings().simli_api_key
    out = str(text or "")
    if key:
        out = out.replace(key, "***")
    return out[:300]


class PassThroughOnFailure:
    """Mixin for an avatar stage: transparent until opened, and again after any failure.

    Place it **before** the service class in the bases so its `process_frame` runs first. The
    concrete service supplies `_start_avatar` and `_stop_avatar`.
    """

    _avatar_open = False       # the vendor session has been asked for (so it must be closed with the call)
    _avatar_ready = False      # ... and has actually come up: only then does the stage consume speech
    _avatar_failed = False
    _on_failure: OnFailure | None = None
    _pending: list | None = None          # speech sent to the vendor that has not come back yet
    _pending_bytes = 0
    _pending_since: float | None = None
    _returned = 0                         # count of audio frames the vendor has handed back
    _flushing = False
    _watch_task: asyncio.Task | None = None
    _first_video: asyncio.Event | None = None

    def configure_failure(self, on_failure: OnFailure | None) -> None:
        self._on_failure = on_failure

    @property
    def avatar_open(self) -> bool:
        return self._avatar_open

    @property
    def avatar_failed(self) -> bool:
        return self._avatar_failed

    # -- lifetime (AV-07): the vendor session starts when someone is there, and ends with the call
    async def open_avatar(self) -> None:
        if self._avatar_open or self._avatar_failed:
            return
        limit = get_settings().avatar_max_sessions
        if len(_LIVE) >= limit:
            # Our own cap, set below the vendor's, so a busy deployment degrades to an ordinary
            # video call instead of being refused by the vendor mid-welcome (AV-11).
            await self._fail(f"already {limit} avatar session(s) open in this process")
            return
        self._avatar_open = True
        _LIVE.add(self)
        self._first_video = asyncio.Event()
        try:
            await asyncio.wait_for(self._start_avatar(), OPEN_TIMEOUT_S)
            await self._await_proof_of_life()
            self._avatar_ready = not self._avatar_failed
        except TimeoutError:
            await self._fail(f"opening the avatar session took longer than {OPEN_TIMEOUT_S:g}s")
        except Exception as exc:  # noqa: BLE001 - a vendor failure must never end a call
            await self._fail(exc)

    async def _await_proof_of_life(self) -> None:
        """Give an explicit refusal the chance to arrive before the stage starts consuming speech.

        Returns as soon as the vendor shows a frame or the stage has failed. If neither happens the
        session is trusted anyway: silence does not prove a refusal, and a false failure would
        cost every call its face (AV-10).
        """
        assert self._first_video is not None
        deadline = time.monotonic() + READY_PROOF_S
        while not self._first_video.is_set() and not self._avatar_failed and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    def vendor_ended(self, reason: str) -> None:
        """The vendor said the session is over (an error, a rate limit, a close). Never raises.

        Called from the vendor SDK's event callbacks, so it only schedules the failure.
        """
        if self._avatar_open and not self._avatar_failed:
            asyncio.get_running_loop().create_task(self._fail(reason))

    async def close_avatar(self) -> None:
        was_open = self._avatar_open
        self._avatar_open = False
        self._avatar_ready = False
        _LIVE.discard(self)
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        if not was_open:
            return
        try:
            await self._stop_avatar()
        except Exception as exc:  # noqa: BLE001
            log.warning("avatar did not close cleanly: %s", scrub(f"{type(exc).__name__}: {exc}"))

    async def _start_avatar(self) -> None:
        raise NotImplementedError

    async def _stop_avatar(self) -> None:
        return None

    # -- failure (AV-05)
    async def _fail(self, exc: BaseException | str) -> None:
        if self._avatar_failed:
            return
        self._avatar_failed = True
        self._avatar_ready = False
        _LIVE.discard(self)  # a failed session no longer counts against the cap
        reason = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        log.warning("avatar unavailable, passing the agent's speech through: %s", scrub(reason))
        await self._flush_pending()  # speech the vendor swallowed is heard late rather than never
        try:
            await self._stop_avatar()  # best effort: stop paying for a session that is not working
        except Exception:  # noqa: BLE001
            pass
        if self._on_failure is not None:
            try:
                await self._on_failure(scrub(reason))
            except Exception:  # noqa: BLE001
                pass

    async def push_error(self, error_msg: str, exception: Exception | None = None, **kwargs: Any) -> None:
        """The vendor service reports its own errors this way; any of them means "stop relying on it"."""
        await self._fail(exception or error_msg)
        # The ErrorFrame carries the exception object to every handler upstream, and a vendor
        # exception can echo the key, so what travels on is a scrubbed copy (AV-08).
        safe = RuntimeError(scrub(f"{type(exception).__name__}: {exception}")) if exception else None
        await super().push_error(scrub(error_msg), safe, **kwargs)  # type: ignore[misc]

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, _RENDERED) and (self._avatar_failed or not self._avatar_ready):
            # Not rendering, so these are not ours to consume. Base bookkeeping still runs; the
            # vendor logic does not.
            await FrameProcessor.process_frame(self, frame, direction)  # type: ignore[arg-type]
            await self.push_frame(frame, direction)  # type: ignore[attr-defined]
            return
        returned_before = self._returned
        try:
            await super().process_frame(frame, direction)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            await self._fail(exc)
            if isinstance(frame, TTSAudioRawFrame):
                await self.push_frame(frame, direction)  # type: ignore[attr-defined]  # the agent must still be heard
            return
        if isinstance(frame, TTSAudioRawFrame) and not self._avatar_failed and self._returned == returned_before:
            self._remember(frame)  # consumed: held until the vendor hands the speech back

    # -- the watchdog: speech sent to the vendor must come back (AV-05)
    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        if isinstance(frame, OutputImageRawFrame) and self._first_video is not None:
            self._first_video.set()  # the vendor is rendering: the session is real
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TTSAudioRawFrame) and not self._flushing:
            # Audio leaving this stage is either the vendor's re-timed speech coming back, or a
            # pass-through. Either way what we were holding has been delivered.
            self._returned += 1
            self._pending, self._pending_bytes, self._pending_since = [], 0, None
        await super().push_frame(frame, direction)  # type: ignore[misc]

    def _remember(self, frame: TTSAudioRawFrame) -> None:
        if self._pending is None:
            self._pending = []
        self._pending.append(frame)
        self._pending_bytes += len(frame.audio)
        while self._pending_bytes > MAX_PENDING_BYTES and self._pending:
            self._pending_bytes -= len(self._pending.pop(0).audio)
        if self._pending_since is None:
            self._pending_since = time.monotonic()
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.get_running_loop().create_task(self._watch())

    async def _watch(self) -> None:
        while self._pending and not self._avatar_failed:
            await asyncio.sleep(0.25)
            since = self._pending_since
            if self._pending and since is not None and time.monotonic() - since >= RETURN_TIMEOUT_S:
                await self._fail(f"the avatar returned no audio within {RETURN_TIMEOUT_S:g}s")
                return

    async def _flush_pending(self) -> None:
        frames, self._pending = self._pending or [], []
        self._pending_bytes, self._pending_since = 0, None
        if not frames:
            return
        self._flushing = True
        try:
            for held in frames:
                await self.push_frame(held, FrameDirection.DOWNSTREAM)
        finally:
            self._flushing = False


@lru_cache(maxsize=1)
def _guarded_simli_class() -> type:
    """The Simli service with the pass-through guard, built on first use so the SDK loads lazily."""
    from pipecat.services.simli.video import SimliVideoService

    class GuardedSimli(PassThroughOnFailure, SimliVideoService):  # type: ignore[misc, valid-type]
        async def setup(self, setup: Any) -> None:
            # The stock service opens its vendor session here, at pipeline start. We open it later,
            # when a participant has joined, so an empty room costs nothing (AV-07).
            await super(SimliVideoService, self).setup(setup)

        async def _start_avatar(self) -> None:
            await SimliVideoService._start_connection(self)
            if not self._initialized:  # the stock service swallows the error and pushes it
                raise RuntimeError("the avatar connection did not start")
            self._listen_for_vendor_end()

        def _listen_for_vendor_end(self) -> None:
            """The SDK turns a rate limit or error into an ERROR event and lets the socket die, without
            raising anywhere. Listen for it so the stage fails over at once, not after 5 s (AV-10).

            STOP is deliberately not listened to: the SDK also maps its `ENDFRAME` marker to it, which
            appears to be the end of an utterance, not of the session."""
            from simli.events import SimliEvent

            async def ended() -> None:
                self.vendor_ended("the avatar service reported an error or a limit")

            try:
                self._simli_client.registerEventCallback(SimliEvent.ERROR, ended)
            except Exception as exc:  # noqa: BLE001 - listening is best effort; the watchdog still guards
                log.warning("could not listen for avatar errors: %s", scrub(str(exc)))

        async def _stop_avatar(self) -> None:
            await self._stop_connection()

    return GuardedSimli


def make_avatar(on_failure: OnFailure | None = None) -> PassThroughOnFailure:
    """Build the avatar stage for one call. Constructs no network connection (VO-06)."""
    s = get_settings()
    avatar = _guarded_simli_class()(api_key=s.simli_api_key, face_id=s.simli_face_id)
    avatar.configure_failure(on_failure)
    return avatar


async def close_all_avatars() -> None:
    """Close every vendor session this process still holds (AV-12). Idempotent."""
    for avatar in list(_LIVE):
        try:
            await avatar.close_avatar()
        except Exception as exc:  # noqa: BLE001
            log.warning("avatar did not close at shutdown: %s", scrub(f"{type(exc).__name__}: {exc}"))
    _LIVE.clear()
