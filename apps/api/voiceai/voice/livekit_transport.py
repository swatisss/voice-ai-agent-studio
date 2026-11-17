"""The LiveKit side of a hosted media room: the AI participant, the scribe, control messages, closing the room.

Spec: /architecture/hosted-media-room.md (LKH-03, LKH-08, LKH-09, LKH-13), /decisions/adr-0015-hosted-media-room-livekit.md

Pipecat and LiveKit imports stay in `voiceai/voice/`, and the LiveKit SDK (`livekit`, `livekit-api`, Pipecat's LiveKit
transport) is imported only inside the functions that open a room, so the rest of the app and the whole test suite run
without it being used and without credentials. `voiceai.media_room` owns the rules and talks to this module only through
`LiveKitBackend` (the `RoomBackend` protocol); tests replace it with a fake.

UNVERIFIED against a real LiveKit Cloud project (no account yet): the logic around the SDK is covered by unit tests with
fakes; the SDK calls themselves are exercised by `scripts/livekit_check.py` and the two-machine demo in
/build/runbook-livekit.md.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, EndFrame, InputAudioRawFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai import media_room
from voiceai.config import get_settings
from voiceai.media_room import PREFIX, RoomState, RoomUnavailable

log = logging.getLogger("voiceai.livekit")


# ---------------------------------------------------------------- pipeline pieces (pure frame logic, unit-tested)
def is_customer(identity: str | None) -> bool:
    return bool(identity) and str(identity).startswith(PREFIX["customer"])


class CustomerAudioOnly(FrameProcessor):
    """LKH-03: the model hears the customer and nobody else. Audio frames carry the speaker's identity (`user_id`);
    anything not from a `cust-` identity is dropped here, before speech recognition."""

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:  # noqa: ANN401
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and not is_customer(getattr(frame, "user_id", None)):
            return
        await self.push_frame(frame, direction)


class SpokenWatcher(FrameProcessor):
    """Tells `say()` when a fixed line has been played to the end (the bot started and then stopped speaking)."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(**kwargs)
        self.spoken = asyncio.Event()
        self._armed = False
        self._started = False

    def arm(self) -> None:
        self.spoken.clear()
        self._armed, self._started = True, False

    async def process_frame(self, frame: Any, direction: FrameDirection) -> None:  # noqa: ANN401
        await super().process_frame(frame, direction)
        if self._armed and isinstance(frame, BotStartedSpeakingFrame):
            self._started = True
        elif self._armed and self._started and isinstance(frame, BotStoppedSpeakingFrame):
            self._armed = False
            self.spoken.set()
        await self.push_frame(frame, direction)


@dataclass
class RoomLink:
    """What `pipeline.make_transport` needs to put the AI into a room (instead of a socket)."""

    url: str
    token: str
    room: str
    watcher: SpokenWatcher = field(default_factory=SpokenWatcher)


def http_url(ws_url: str) -> str:
    """The server API lives on https while the browser and the SDK use wss."""
    return ws_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)


# ---------------------------------------------------------------- the backend
@dataclass
class _AIRun:
    task: asyncio.Task[None]
    pipeline: Any = None
    link: RoomLink | None = None
    stopping: bool = False


class LiveKitBackend:
    """The real `RoomBackend`. One instance per process."""

    def __init__(self) -> None:
        self._ai: dict[str, _AIRun] = {}
        self._scribes: dict[str, Any] = {}

    # -- the AI participant
    async def start_ai(self, state: RoomState, session: Any) -> None:  # noqa: ANN401
        from voiceai import admission, call_settings
        from voiceai.db import sessionmaker
        from voiceai.live import LiveControls, follow
        from voiceai.models import Call
        from voiceai.voice import pipeline

        settings = get_settings()
        try:
            async with sessionmaker()() as s:
                call = await s.get(Call, state.call_id)
                config = (await call_settings.load(s, call)).config
                decided = await admission.admit_socket(s, state.tenant_id, config, (call.meta or {}).get("admission"))
        except Exception as exc:  # noqa: BLE001
            raise RoomUnavailable("admission") from exc
        if isinstance(decided, admission.Refusal):
            raise RoomUnavailable(decided.reason)
        _, key = decided
        token = media_room.mint("ai", state.room, media_room.identity_for("ai", state.call_id))["token"]
        link = RoomLink(settings.livekit_url or "", token, state.room)
        controls = LiveControls(turn=session.turn_settings())
        unfollow = follow(session, controls)
        task, transport, brain, _ = pipeline.build(link, session, key, controls)  # type: ignore[arg-type]
        joined: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        run = _AIRun(asyncio.create_task(asyncio.sleep(0)), task, link)
        greeted = False

        async def greet_if_customer() -> None:
            nonlocal greeted
            if not greeted and any(is_customer(p) for p in transport.get_participants()):
                greeted = True
                await brain.greet()

        @transport.event_handler("on_connected")
        async def _connected(_t: Any) -> None:  # noqa: ANN401
            if not joined.done():
                joined.set_result(None)
            await greet_if_customer()

        @transport.event_handler("on_participant_connected")
        async def _arrived(_t: Any, participant_id: str) -> None:  # noqa: ANN401
            await greet_if_customer()
            await media_room.participant_connected(state.call_id, participant_id)

        @transport.event_handler("on_participant_disconnected")
        async def _left(_t: Any, participant_id: str) -> None:  # noqa: ANN401
            await media_room.participant_disconnected(state.call_id, participant_id)

        async def runner() -> None:
            from pipecat.pipeline.runner import PipelineRunner

            try:
                await PipelineRunner(handle_sigint=False).run(task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - LKH-13: LiveKit refused the join or dropped us
                if not joined.done():
                    joined.set_exception(RoomUnavailable(type(exc).__name__))
                else:
                    log.warning("AI pipeline in %s failed: %s", state.room, type(exc).__name__)
            finally:
                unfollow()
                if not joined.done():
                    joined.set_exception(RoomUnavailable("closed"))
                if not run.stopping and not state.ended:  # the pipeline died with the AI still in charge
                    await media_room.end_call(state, "error")

        run.task = asyncio.create_task(runner())
        self._ai[state.call_id] = run
        await joined

    async def say(self, call_id: str, text: str) -> None:
        run = self._ai.get(call_id)
        if run is None or run.link is None:
            return
        run.link.watcher.arm()
        await run.pipeline.queue_frame(TTSSpeakFrame(text))
        await run.link.watcher.spoken.wait()  # the caller bounds this wait (LKH-08: 10 s)

    async def stop_ai(self, call_id: str) -> None:
        run = self._ai.pop(call_id, None)
        if run is None:
            return
        run.stopping = True
        with contextlib.suppress(Exception):
            await run.pipeline.queue_frame(EndFrame())
        try:
            await asyncio.wait_for(asyncio.shield(run.task), 5)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            run.task.cancel()

    # -- the scribe
    async def start_scribe(self, state: RoomState) -> None:
        from voiceai.voice.scribe import Scribe

        scribe = Scribe(state, get_settings().deepgram_api_key or "")
        await scribe.start()
        self._scribes[state.room] = scribe

    # -- control messages and the room itself (server API over https, no media)
    async def send(self, room: str, message: dict[str, Any]) -> None:
        import json

        from livekit import api

        settings = get_settings()
        async with api.LiveKitAPI(http_url(settings.livekit_url or ""), settings.livekit_api_key, settings.livekit_api_secret) as lk:
            await lk.room.send_data(api.SendDataRequest(
                room=room, data=json.dumps(message).encode(), kind=0, topic=media_room.CONTROL_TOPIC))  # kind 0 = reliable delivery

    async def close_room(self, room: str) -> None:
        from livekit import api

        scribe = self._scribes.pop(room, None)
        if scribe is not None:
            await scribe.stop()
        settings = get_settings()
        async with api.LiveKitAPI(http_url(settings.livekit_url or ""), settings.livekit_api_key, settings.livekit_api_secret) as lk:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))

