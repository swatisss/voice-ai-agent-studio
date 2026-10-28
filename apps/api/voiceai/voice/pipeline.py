"""Builds and runs the Pipecat voice pipeline for one call.

Spec: /architecture/voice-pipeline.md, /architecture/realtime-voice.md, /architecture/telephony.md, /api/voice-protocol.md
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

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

from voiceai import telephony
from voiceai.config import get_settings
from voiceai.live import LiveControls
from voiceai.runtime.session import AgentSession
from voiceai.voice.phone import PhoneSerializer, PhoneStream
from voiceai.voice.processors import BrainProcessor, TurnAggregator
from voiceai.voice.realtime import Connector, RealtimeBridge, RealtimeConnection, RATE as REALTIME_RATE
from voiceai.voice.turn_detection import TurnEvaluator
from voiceai.voice.serializer import IN_RATE, OUT_RATE, RawPCMSerializer

log = logging.getLogger("voiceai.voice")


def make_transport(websocket: WebSocket, phone: PhoneStream | None, in_rate: int, out_rate: int) -> tuple[FastAPIWebsocketTransport, RawPCMSerializer | PhoneSerializer]:
    """The transport profile: `browser` (raw PCM + JSON control messages) or `twilio` (mu-law 8 kHz Media Stream events)."""
    serializer: RawPCMSerializer | PhoneSerializer = PhoneSerializer(phone.stream_sid, phone.call_sid) if phone else RawPCMSerializer()
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_in_sample_rate=in_rate, audio_out_enabled=True, audio_out_sample_rate=out_rate,
            add_wav_header=False, serializer=serializer, session_timeout=3600,
        ),
    )
    return transport, serializer


class CallEnder:
    """The end-of-call sequence shared by both pipelines: record the reason for the serializer, end the session,
    transfer a phone call before its stream closes (TEL-07), then stop the pipeline."""

    def __init__(self, session: AgentSession, serializer: RawPCMSerializer | PhoneSerializer, phone: PhoneStream | None) -> None:
        self.session, self.serializer, self.phone = session, serializer, phone
        self.task: PipelineTask | None = None

    async def __call__(self, reason: str) -> None:
        self.serializer.end_reason = reason
        await self.session.end(reason)
        if self.phone:  # TEL-07: the transfer must happen before the stream closes
            await telephony.on_phone_end(self.session, reason, self.phone.call_sid)
        if self.task:
            await self.task.queue_frame(EndFrame())


async def run_call(
    task: PipelineTask, transport: FastAPIWebsocketTransport, session: AgentSession, greet: Callable[[], Awaitable[None]],
    shutdown: Callable[[], Awaitable[None]] | None = None, hangup_is_normal: bool = False,
) -> None:
    """Greet when the caller connects, end the session on hang-up, run the pipeline to its end.

    With `hangup_is_normal`, the cancellation caused by the caller hanging up is a normal end rather than an error.
    """
    hung_up = False

    @transport.event_handler("on_client_connected")
    async def _connected(_transport, _ws) -> None:  # noqa: ANN001
        await greet()

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _ws) -> None:  # noqa: ANN001
        nonlocal hung_up
        hung_up = True
        await session.end("hangup")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        if not (hangup_is_normal and hung_up):  # cancelled from outside: propagate
            raise
    finally:
        if shutdown:
            await shutdown()
        await session.end("hangup")


def build(
    websocket: WebSocket, session: AgentSession, deepgram_key: str, controls: LiveControls | None = None,
    phone: PhoneStream | None = None,
) -> tuple[PipelineTask, FastAPIWebsocketTransport, BrainProcessor, RawPCMSerializer | PhoneSerializer]:
    """Construct the cascade pipeline without network I/O (VO-06)."""
    settings = get_settings()
    controls = controls or LiveControls(turn=session.turn_settings())
    transport, serializer = make_transport(websocket, phone, IN_RATE, OUT_RATE)
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=settings.voice_vad_stop_secs)))
    stt = DeepgramSTTService(
        api_key=deepgram_key,
        sample_rate=IN_RATE,
        settings=DeepgramSTTService.Settings(
            model=settings.deepgram_stt_model, language="en-US", smart_format=True, punctuate=True, interim_results=True,
        ),
    )
    voice, speed = session.call_settings.cascade_voice
    tts = DeepgramTTSService(api_key=deepgram_key, sample_rate=OUT_RATE, settings=DeepgramTTSService.Settings(voice=voice, speed=speed))
    on_end = CallEnder(session, serializer, phone)
    brain = BrainProcessor(session, on_end, controls)
    turns = TurnAggregator(
        controls, TurnEvaluator(), last_agent_text=lambda: last_agent_message(session),
        vad_stop_ms=int(settings.voice_vad_stop_secs * 1000), welcoming=lambda: brain.floor.welcoming,
    )

    async def apply_voice(voice: str, speed: float) -> None:  # live persona switch: next sentence uses the new voice
        if on_end.task:
            await on_end.task.queue_frame(TTSUpdateSettingsFrame(delta=DeepgramTTSService.Settings(voice=voice, speed=speed)))

    controls.on_voice = apply_voice
    pipeline = Pipeline([transport.input(), vad, stt, turns, brain, tts, transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))
    on_end.task = task
    return task, transport, brain, serializer


def last_agent_message(session: AgentSession) -> str | None:
    for m in reversed(session.history):
        if m.get("role") == "assistant" and m.get("content"):
            return str(m["content"])
    return None


async def run(websocket: WebSocket, session: AgentSession, deepgram_key: str, controls: LiveControls | None = None, phone: PhoneStream | None = None) -> None:
    task, transport, brain, _ = build(websocket, session, deepgram_key, controls, phone)
    await run_call(task, transport, session, brain.greet)


def build_realtime(
    websocket: WebSocket, session: AgentSession, controls: LiveControls, conn: RealtimeConnection,
    phone: PhoneStream | None = None,
) -> tuple[PipelineTask, FastAPIWebsocketTransport, RealtimeBridge, RawPCMSerializer | PhoneSerializer]:
    """The speech-to-speech pipeline: transport in, RealtimeBridge, transport out (RV-02). No network here."""
    transport, serializer = make_transport(websocket, phone, REALTIME_RATE if phone else IN_RATE, REALTIME_RATE)
    on_end = CallEnder(session, serializer, phone)
    bridge = RealtimeBridge(session, controls, conn, on_end, send_ready=phone is None)
    pipeline = Pipeline([transport.input(), bridge, transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=REALTIME_RATE if phone else IN_RATE, audio_out_sample_rate=REALTIME_RATE))
    on_end.task = task
    return task, transport, bridge, serializer


async def run_realtime(
    websocket: WebSocket, session: AgentSession, controls: LiveControls, connector: Connector, phone: PhoneStream | None = None,
) -> None:
    """Open the provider socket first (RV-13: a failure here becomes close code 4500 in the caller), then run the call."""
    conn = await connector()
    task, transport, bridge, _ = build_realtime(websocket, session, controls, conn, phone)
    # the caller hanging up cancels our own pipeline, which is a normal end for the realtime call
    await run_call(task, transport, session, bridge.greet, shutdown=bridge.shutdown, hangup_is_normal=True)
