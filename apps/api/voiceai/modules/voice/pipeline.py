"""Builds and runs the Pipecat voice pipeline for one call.

Spec: /architecture/voice-pipeline.md, /api/voice-protocol.md, /api/media-protocol.md

One pipeline, two transports. A `voice` call runs over the plain WebSocket exactly as it always
has; a `video` call substitutes Pipecat's LiveKit transport at both ends and adds a frame tap
after the input ([ADR-0009](/decisions/adr-0009-video-channel.md)). Everything between the ends -
VAD, STT, TurnAggregator, BrainProcessor, TTS - is the same objects in the same order, which is
the point: there is one brain and one turn loop, not two.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, TTSUpdateSettingsFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from voiceai.core.config import get_settings
from voiceai.modules.conversation.contract import IDLE_LINE, MAX_DURATION_LINE, REMINDER_LINE, AgentSession
from voiceai.modules.voice import frames as frame_tap
from voiceai.modules.voice.controls import LiveControls
from voiceai.modules.voice.processors import BrainProcessor, FrameTap, TurnAggregator
from voiceai.modules.voice.serializer import IN_RATE, OUT_RATE, RawPCMSerializer
from voiceai.modules.voice.turn_detection import TurnEvaluator

log = logging.getLogger("voiceai.voice")


def _parts(session: AgentSession, deepgram_key: str, controls: LiveControls) -> dict[str, Any]:
    """Everything between the two transport ends. Identical for both channels."""
    settings = get_settings()
    persona = session.config.get("persona") or {}
    return {
        "vad": VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=settings.voice_vad_stop_secs))),
        "stt": DeepgramSTTService(
            api_key=deepgram_key,
            sample_rate=IN_RATE,
            settings=DeepgramSTTService.Settings(
                model=settings.deepgram_stt_model, language="en-US", smart_format=True,
                punctuate=True, interim_results=True,
            ),
        ),
        "tts": DeepgramTTSService(
            api_key=deepgram_key, sample_rate=OUT_RATE,
            settings=DeepgramTTSService.Settings(
                voice=persona.get("voice") or "aura-2-thalia-en", speed=float(persona.get("speed") or 1.0)
            ),
        ),
        "turns": TurnAggregator(
            controls, TurnEvaluator(), last_agent_text=lambda: last_agent_message(session),
            vad_stop_ms=int(settings.voice_vad_stop_secs * 1000),
        ),
    }


def _assemble(
    transport: Any, session: AgentSession, controls: LiveControls, parts: dict[str, Any],
    middle: list[Any] | None = None, serializer: RawPCMSerializer | None = None,
) -> tuple[PipelineTask, BrainProcessor]:
    task_holder: dict[str, Any] = {}

    async def on_end(reason: str) -> None:
        if serializer is not None:
            serializer.end_reason = reason
        await session.end(reason)
        task = task_holder.get("task")
        if task:
            await task.queue_frame(EndFrame())

    brain = BrainProcessor(session, on_end, controls)

    async def apply_voice(voice: str, speed: float) -> None:  # live persona switch
        await task_holder["task"].queue_frame(
            TTSUpdateSettingsFrame(delta=DeepgramTTSService.Settings(voice=voice, speed=speed))
        )

    controls.on_voice = apply_voice
    pipeline = Pipeline(
        [transport.input(), *(middle or []), parts["vad"], parts["stt"], parts["turns"], brain,
         parts["tts"], transport.output()]
    )
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))
    task_holder["task"] = task
    return task, brain


# ---------------------------------------------------------------- voice: the WebSocket transport
def build(
    websocket: WebSocket, session: AgentSession, deepgram_key: str, controls: LiveControls | None = None,
) -> tuple[PipelineTask, FastAPIWebsocketTransport, BrainProcessor, RawPCMSerializer]:
    """Construct the pipeline without network I/O (VO-06)."""
    controls = controls or LiveControls(turn=session.turn_settings())
    serializer = RawPCMSerializer()
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_in_sample_rate=IN_RATE,
            audio_out_enabled=True,
            audio_out_sample_rate=OUT_RATE,
            add_wav_header=False,
            serializer=serializer,
            session_timeout=3600,
        ),
    )
    task, brain = _assemble(transport, session, controls, _parts(session, deepgram_key, controls), serializer=serializer)
    return task, transport, brain, serializer


def last_agent_message(session: AgentSession) -> str | None:
    for m in reversed(session.history):
        if m.get("role") == "assistant" and m.get("content"):
            return str(m["content"])
    return None


async def run(websocket: WebSocket, session: AgentSession, deepgram_key: str, controls: LiveControls | None = None) -> None:
    task, transport, brain, _ = build(websocket, session, deepgram_key, controls)

    @transport.event_handler("on_client_connected")
    async def _connected(_transport, _ws) -> None:  # noqa: ANN001
        await brain.greet()

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _ws) -> None:  # noqa: ANN001
        await session.end("hangup")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        raise
    finally:
        await session.end("hangup")


# ---------------------------------------------------------------- video: the LiveKit transport
def build_room(
    session: AgentSession, deepgram_key: str, url: str, token: str, room: str,
    controls: LiveControls | None = None, holder: Any | None = None,
) -> tuple[PipelineTask, Any, BrainProcessor]:
    """Construct the LiveKit pipeline without network I/O (VO-06, now for both transports).

    `video_in_enabled` is on and no video track is published: the agent subscribes to the caller's
    camera and sends none of its own. An avatar track would go here, and is a separate CP
    ([/product/scope.md](/product/scope.md)).
    """
    from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

    controls = controls or LiveControls(turn=session.turn_settings())
    holder = holder if holder is not None else frame_tap.register(session.call_id)
    transport = LiveKitTransport(
        url=url, token=token, room_name=room,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_in_sample_rate=IN_RATE,
            audio_out_enabled=True,
            audio_out_sample_rate=OUT_RATE,
            video_in_enabled=True,
            video_out_enabled=False,
            vad_analyzer=None,
        ),
    )
    task, brain = _assemble(
        transport, session, controls, _parts(session, deepgram_key, controls),
        middle=[FrameTap(holder)],
    )
    return task, transport, brain


async def run_room(call_id: str, tenant_id: str) -> None:
    """Join the call's room, run the brain, and end the call when the caller leaves.

    The welcome is spoken on the first participant joining, which is the room's equivalent of the
    WebSocket's `on_client_connected` - so VO-07's "speaks first" holds on both channels.
    """
    from voiceai.core.config import get_settings
    from voiceai.modules.conversation.contract import open_session
    from voiceai.modules.voice.controls import LIVE
    from voiceai.modules.voice.room import JOIN_TIMEOUT_S, LiveKitVideoRoom, room_name

    settings = get_settings()
    key = settings.deepgram_api_key
    if not key:
        log.error("video call %s cannot start: DEEPGRAM_API_KEY is not set", call_id)
        return

    session = await open_session(call_id, tenant_id)
    policy = session.config.get("policy") or {}
    max_seconds = int(policy.get("max_call_seconds") or 600)
    rooms = LiveKitVideoRoom()
    controls = LiveControls(turn=session.turn_settings())
    LIVE[call_id] = controls
    holder = frame_tap.register(call_id)
    joined = asyncio.Event()

    task, transport, brain = build_room(
        session, key, str(settings.livekit_url), rooms.agent_token(call_id, max_seconds),
        room_name(call_id), controls, holder,
    )

    @transport.event_handler("on_first_participant_joined")
    async def _joined(_transport, participant_id: str) -> None:  # noqa: ANN001
        joined.set()
        await brain.greet()

    @transport.event_handler("on_participant_disconnected")
    async def _left(_transport, participant_id: str) -> None:  # noqa: ANN001
        await session.end("hangup")
        await task.cancel()

    @transport.event_handler("on_video_track_subscribed")
    async def _camera_on(_transport, participant_id: str) -> None:  # noqa: ANN001
        holder.camera_on = True  # frames follow; the tap fills in

    @transport.event_handler("on_video_track_unsubscribed")
    async def _camera_off(_transport, participant_id: str) -> None:  # noqa: ANN001
        holder.camera_off()  # drop the stale frame, so a later look is declined (VI-15)

    async def _abandon_if_nobody_joins() -> None:
        try:
            await asyncio.wait_for(joined.wait(), JOIN_TIMEOUT_S)
        except TimeoutError:
            log.info("video call %s: nobody joined in %ss, ending", call_id, JOIN_TIMEOUT_S)
            await session.end("hangup")
            await task.cancel()

    watchdog = asyncio.create_task(_abandon_if_nobody_joins())
    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        raise
    finally:
        watchdog.cancel()
        frame_tap.release(call_id)
        LIVE.pop(call_id, None)
        await session.end("hangup")
