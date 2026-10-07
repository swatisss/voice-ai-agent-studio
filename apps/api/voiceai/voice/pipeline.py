"""Builds and runs the Pipecat voice pipeline for one call.

Spec: /architecture/voice-pipeline.md, /api/voice-protocol.md
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

from voiceai.config import get_settings
from voiceai.live import LiveControls
from voiceai.runtime.session import AgentSession
from voiceai.voice.processors import BrainProcessor, TurnAggregator
from voiceai.voice.turn_detection import TurnEvaluator
from voiceai.voice.serializer import IN_RATE, OUT_RATE, RawPCMSerializer

log = logging.getLogger("voiceai.voice")


def build(
    websocket: WebSocket, session: AgentSession, deepgram_key: str, controls: LiveControls | None = None,
) -> tuple[PipelineTask, FastAPIWebsocketTransport, BrainProcessor, RawPCMSerializer]:
    """Construct the pipeline without network I/O (VO-06)."""
    settings = get_settings()
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
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=settings.voice_vad_stop_secs)))
    stt = DeepgramSTTService(
        api_key=deepgram_key,
        sample_rate=IN_RATE,
        settings=DeepgramSTTService.Settings(
            model=settings.deepgram_stt_model, language="en-US", smart_format=True, punctuate=True, interim_results=True,
        ),
    )
    persona = session.config.get("persona") or {}
    tts = DeepgramTTSService(
        api_key=deepgram_key, sample_rate=OUT_RATE,
        settings=DeepgramTTSService.Settings(voice=persona.get("voice") or "aura-2-thalia-en", speed=float(persona.get("speed") or 1.0)),
    )
    turns = TurnAggregator(controls, TurnEvaluator(), last_agent_text=lambda: last_agent_message(session), vad_stop_ms=int(settings.voice_vad_stop_secs * 1000))

    task_holder: dict[str, Any] = {}

    async def on_end(reason: str) -> None:
        serializer.end_reason = reason
        await session.end(reason)
        task = task_holder.get("task")
        if task:
            await task.queue_frame(EndFrame())

    brain = BrainProcessor(session, on_end, controls)

    async def apply_voice(voice: str, speed: float) -> None:  # live persona switch: next sentence uses the new voice
        await task_holder["task"].queue_frame(TTSUpdateSettingsFrame(delta=DeepgramTTSService.Settings(voice=voice, speed=speed)))

    controls.on_voice = apply_voice
    pipeline = Pipeline([transport.input(), vad, stt, turns, brain, tts, transport.output()])
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))
    task_holder["task"] = task
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
