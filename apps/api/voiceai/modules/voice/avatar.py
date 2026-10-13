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

import importlib.util
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai.core.config import get_settings

log = logging.getLogger("voiceai.voice")

OnFailure = Callable[[str], Awaitable[None]]

#: The frames a rendering avatar consumes or acts on. When it is not rendering they are forwarded.
_RENDERED = (TTSAudioRawFrame, TTSStoppedFrame, InterruptionFrame, UserStartedSpeakingFrame)


def avatar_available() -> bool:
    """Both Simli settings present and the SDK installed (AV-01).

    Anything less is not an error: the call is an ordinary video call with no face.
    """
    s = get_settings()
    if not (s.simli_api_key and s.simli_face_id):
        return False
    return all(importlib.util.find_spec(name) is not None for name in ("simli", "av"))


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

    _avatar_open = False
    _avatar_failed = False
    _on_failure: OnFailure | None = None

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
        self._avatar_open = True
        try:
            await self._start_avatar()
        except Exception as exc:  # noqa: BLE001 - a vendor failure must never end a call
            await self._fail(exc)

    async def close_avatar(self) -> None:
        was_open = self._avatar_open
        self._avatar_open = False
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
        reason = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        log.warning("avatar unavailable, passing the agent's speech through: %s", scrub(reason))
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
        if isinstance(frame, _RENDERED) and (self._avatar_failed or not self._avatar_open):
            # Not rendering, so these are not ours to consume. Base bookkeeping still runs; the
            # vendor logic does not.
            await FrameProcessor.process_frame(self, frame, direction)  # type: ignore[arg-type]
            await self.push_frame(frame, direction)  # type: ignore[attr-defined]
            return
        try:
            await super().process_frame(frame, direction)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            await self._fail(exc)
            if isinstance(frame, TTSAudioRawFrame):
                await self.push_frame(frame, direction)  # type: ignore[attr-defined]  # the agent must still be heard


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

        async def _stop_avatar(self) -> None:
            await self._stop_connection()

    return GuardedSimli


def make_avatar(on_failure: OnFailure | None = None) -> PassThroughOnFailure:
    """Build the avatar stage for one call. Constructs no network connection (VO-06)."""
    s = get_settings()
    avatar = _guarded_simli_class()(api_key=s.simli_api_key, face_id=s.simli_face_id)
    avatar.configure_failure(on_failure)
    return avatar
