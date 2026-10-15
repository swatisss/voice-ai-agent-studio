"""A fake OpenAI Realtime server and a harness that runs the real Pipecat service against it.

Not a test module. It lets the realtime brain be exercised end to end - the real OpenAI service,
the real context aggregators, our gate and brain - with no key and no network.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import websockets
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

SESSION = {"type": "realtime", "model": "gpt-realtime-2.1"}


class FakeRealtime:
    """Speaks just enough of the Realtime protocol to drive the service."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.ws: Any = None
        self.url = ""
        self._server: Any = None
        self.updated = asyncio.Event()
        self._n = 0

    async def start(self) -> str:
        async def handler(ws: Any) -> None:
            self.ws = ws
            await ws.send(json.dumps({"type": "session.created", "event_id": "e0", "session": SESSION}))
            async for raw in ws:
                evt = json.loads(raw)
                self.received.append(evt)
                if evt["type"] == "session.update":
                    await ws.send(json.dumps({"type": "session.updated", "event_id": "eu", "session": SESSION}))
                    self.updated.set()

        self._server = await websockets.serve(handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self.url

    async def stop(self) -> None:
        """Close the connection and the server. Bounded: a test's teardown must never hang."""
        if self.ws is not None:
            try:
                await asyncio.wait_for(self.ws.close(), 2)
            except Exception:  # noqa: BLE001
                pass
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), 2)
            except Exception:  # noqa: BLE001
                pass

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.received if e["type"] == kind]

    async def wait_for(self, kind: str, count: int = 1, timeout: float = 3.0) -> list[dict[str, Any]]:
        async def poll() -> None:
            while len(self.of(kind)) < count:
                await asyncio.sleep(0.02)
        await asyncio.wait_for(poll(), timeout)
        return self.of(kind)

    async def send(self, evt: dict[str, Any]) -> None:
        self._n += 1
        await self.ws.send(json.dumps({"event_id": f"s{self._n}", **evt}))

    # -- scripted server behaviour
    async def caller_says(self, text: str, item: str = "u1") -> None:
        await self.send({"type": "input_audio_buffer.speech_started", "audio_start_ms": 0, "item_id": item})
        await self.send({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 500, "item_id": item})
        await self.send({"type": "conversation.item.input_audio_transcription.completed", "item_id": item,
                         "content_index": 0, "transcript": text})

    async def agent_says(self, text: str, resp: str = "r1", item: str = "a1", usage: bool = True,
                         audio_bytes: int = 4800) -> None:
        await self.send({"type": "conversation.item.added",
                         "item": {"id": item, "type": "message", "role": "assistant", "status": "in_progress", "content": []}})
        audio = base64.b64encode(b"\x01\x00" * (audio_bytes // 2)).decode()
        await self.send({"type": "response.output_audio.delta", "response_id": resp, "item_id": item,
                         "output_index": 0, "content_index": 0, "delta": audio})
        await self.send({"type": "response.output_audio_transcript.delta", "response_id": resp, "item_id": item,
                         "output_index": 0, "content_index": 0, "delta": text})
        await self.response_done(resp, usage)

    async def response_done(self, resp: str = "r1", usage: bool = True) -> None:
        body: dict[str, Any] = {"id": resp, "object": "realtime.response", "status": "completed", "status_details": None, "output": []}
        if usage:
            body["usage"] = {"total_tokens": 1000, "input_tokens": 600, "output_tokens": 400,
                             "input_token_details": {"text_tokens": 100, "audio_tokens": 500, "cached_tokens": 0},
                             "output_token_details": {"text_tokens": 100, "audio_tokens": 300}}
        await self.send({"type": "response.done", "response": body})

    async def calls_tool(self, name: str, args: dict[str, Any], call_id: str = "c1", item: str = "f1") -> None:
        await self.send({"type": "conversation.item.added",
                         "item": {"id": item, "type": "function_call", "status": "in_progress", "name": name,
                                  "call_id": call_id, "arguments": ""}})
        await self.send({"type": "response.function_call_arguments.done", "response_id": "r-tool", "item_id": item,
                         "output_index": 0, "call_id": call_id, "arguments": json.dumps(args)})


class FakeOutput(FrameProcessor):
    """Stands in for the transport output: plays what it is given and reports the agent speaking."""

    def __init__(self, play_s: float = 0.05) -> None:
        super().__init__()
        self.audio: list[bytes] = []
        self.play_s = play_s
        self._speaking = False
        self._timer: asyncio.Task[None] | None = None

    async def _stop_later(self) -> None:
        await asyncio.sleep(self.play_s)
        self._speaking = False
        await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self.audio.append(frame.audio)
            if not self._speaking:
                self._speaking = True
                await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
                await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            if self._timer:
                self._timer.cancel()
            self._timer = asyncio.create_task(self._stop_later())
        await self.push_frame(frame, direction)


class Harness:
    """The realtime pipeline minus the LiveKit transport, running against a FakeRealtime."""

    def __init__(self, session: Any, fake: FakeRealtime, controls: Any, *, deepgram_key: str = "") -> None:
        from voiceai.modules.voice import realtime

        self.ended: list[str] = []
        self.out = FakeOutput()
        self.task: PipelineTask | None = None
        self._runner_task: asyncio.Task[None] | None = None

        async def on_end(reason: str) -> None:
            self.ended.append(reason)
            await session.end(reason)

        self.pieces = realtime.build_realtime(session, controls, on_end, deepgram_key, base_url=fake.url)
        self.pieces.brain.RUN_WATCHDOG = False
        p = self.pieces
        self.pipeline = Pipeline([p.gate, p.user_aggregator, p.tap, p.service, p.brain, self.out, p.assistant_aggregator])

    async def start(self) -> None:
        from pipecat.pipeline.runner import PipelineRunner

        self.task = PipelineTask(
            self.pipeline,
            params=PipelineParams(audio_in_sample_rate=24000, audio_out_sample_rate=24000, enable_usage_metrics=True),
        )
        runner = PipelineRunner(handle_sigint=False)
        self._runner_task = asyncio.create_task(runner.run(self.task))

    async def mic(self, ms: int = 100) -> None:
        assert self.task is not None
        await self.task.queue_frame(InputAudioRawFrame(audio=b"\x00\x00" * (24 * ms), sample_rate=24000, num_channels=1))

    async def stop(self) -> None:
        """Cancel the pipeline. Bounded: a test's teardown must never hang."""
        await self.pieces.brain.drain(3)   # nothing mid-write when the loop is torn down
        if self.task:
            try:
                await asyncio.wait_for(self.task.cancel(), 4)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._runner_task:
            try:
                await asyncio.wait_for(self._runner_task, 4)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
