"""CP-0019, T36: check the OpenAI Realtime model against your real key, and time it.

Spec: /changes/cp-0019-openai-realtime-brain-for-video.md (T36), /architecture/realtime-brain.md

Run from apps/api so the project's settings and `models.yaml` are used:

    cd apps/api && uv run python ../../scripts/realtime_spike.py

It opens one Realtime session with the model and voice the product is configured for, asks the model
to say a sentence, and reports what the account can actually do: whether the model id and the voice
are accepted, how long until the first audio, what the response cost in tokens and dollars at the
prices in `config/models.yaml`. It sends no microphone audio and touches no call, database or room.

It cannot measure the end-to-end figure that matters (end of the caller's speech to the first frame of
the Simli face); that needs a real call. Compare this number with what you see there.
The key is never printed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import websockets

SAY = "Thanks for calling. I am a virtual assistant, and this call may be recorded. How can I help you today?"


async def main() -> int:
    from voiceai.core.config import get_settings
    from voiceai.core.llm.gateway import gateway

    gw = gateway()
    refs = gw.refs_for("speech")
    if not refs:
        print("No usable model in the speech role (models.yaml).")
        return 2
    ref = refs[0]
    model = ref.partition(":")[2]
    key = gw.api_key(ref.partition(":")[0])
    voice = get_settings().realtime_voice
    prices = gw.models.get(ref, {})
    if not key:
        print("OPENAI_API_KEY is not set in apps/api/.env.")
        return 2
    print(f"model {model}   voice {voice}   (from models.yaml / REALTIME_VOICE)")

    async with websockets.connect(
        f"wss://api.openai.com/v1/realtime?model={model}", additional_headers={"Authorization": f"Bearer {key}"},
    ) as ws:
        async def next_event(timeout: float = 15.0) -> dict:
            return json.loads(await asyncio.wait_for(ws.recv(), timeout))

        first = await next_event()
        print("connected:", first.get("type"))
        await ws.send(json.dumps({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["audio"],
            "instructions": "You are a calm, friendly phone assistant.",
            "audio": {"output": {"voice": voice}},
        }}))
        while True:
            evt = await next_event()
            if evt["type"] == "session.updated":
                print("session accepted: model and voice are valid for this account")
                break
            if evt["type"] == "error":
                print("REJECTED:", evt["error"].get("message"))
                return 1

        sent = time.monotonic()
        await ws.send(json.dumps({"type": "response.create", "response": {
            "instructions": "Say exactly the following words, with nothing before or after: " + SAY,
            "tool_choice": "none",
        }}))
        first_audio: float | None = None
        audio_bytes = 0
        text = ""
        usage: dict = {}
        while True:
            evt = await next_event(30)
            kind = evt["type"]
            if kind == "response.output_audio.delta":
                if first_audio is None:
                    first_audio = time.monotonic() - sent
                audio_bytes += len(evt.get("delta", "")) * 3 // 4
            elif kind == "response.output_audio_transcript.delta":
                text += evt.get("delta", "")
            elif kind == "response.done":
                usage = (evt.get("response") or {}).get("usage") or {}
                break
            elif kind == "error":
                print("ERROR:", evt["error"].get("message"))
                return 1
        total = time.monotonic() - sent

    inp, out = usage.get("input_token_details") or {}, usage.get("output_token_details") or {}
    in_a, out_a = int(inp.get("audio_tokens") or 0), int(out.get("audio_tokens") or 0)
    in_t, out_t = int(usage.get("input_tokens") or 0) - in_a, int(usage.get("output_tokens") or 0) - out_a
    cost = (in_t * prices.get("input", 0) + out_t * prices.get("output", 0)
            + in_a * prices.get("input_audio", 0) + out_a * prices.get("output_audio", 0)) / 1e6
    print()
    print(f"asked to say:   {SAY}")
    print(f"it said:        {text.strip()}")
    print(f"exact wording:  {'yes' if text.strip() == SAY else 'NO - the model paraphrased (the spoken welcome and disclosure are only instructed)'}")
    print(f"first audio:    {first_audio * 1000:.0f} ms after the request" if first_audio is not None else "first audio:    none")
    print(f"whole response: {total * 1000:.0f} ms,  {audio_bytes / 48000:.1f} s of audio (24 kHz PCM16)")
    print(f"tokens:         text in {in_t} / out {out_t},  audio in {in_a} / out {out_a}")
    print(f"cost:           ${cost:.4f} at the prices in models.yaml (placeholders until you confirm them)")
    print()
    print("Next: place a real video call and compare the felt delay with 'first audio' above.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
