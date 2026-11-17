"""The `transcribe_handover` job: download a handover recording, transcribe each channel, write the human portion into the call.

Spec: /architecture/phone-warm-handover.md (Recording and transcription, Learning loop), /architecture/jobs-and-events.md

No audio is stored: the media is read into memory, transcribed and dropped. Provider keys never reach a log or a row.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from voiceai import jobs
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.events import bus
from voiceai.handover import _rest, add_event
from voiceai.models import AgentVersion, Call, CallEvent, CallRecording, Escalation, Job
from voiceai.voice import transcribe

log = logging.getLogger("voiceai.handover")


def _scrub(text: str) -> str:
    s = get_settings()
    for secret in (s.twilio_api_key_secret, s.twilio_api_key_sid, s.twilio_auth_token, s.deepgram_api_key):
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"\s+", " ", text)[:300]


async def _download(sid: str, channels: int) -> bytes:
    """`.wav` of the recording with HTTP Basic (API key); `RequestedChannels=2` first, a 400 retries with 1 (spike S3)."""
    s = get_settings()
    auth = (s.twilio_api_key_sid or "", s.twilio_api_key_secret or "")
    for requested in ("2", "1"):
        resp = await _rest("GET", f"Recordings/{sid}.wav", params={"RequestedChannels": requested}, auth=auth)
        if resp.status_code == 400 and requested == "2":
            continue
        if resp.status_code >= 300:
            raise RuntimeError(f"recording download failed: HTTP {resp.status_code}")
        return resp.content
    raise RuntimeError("recording download failed")  # unreachable: the second request returns or raises


async def _delete(sid: str) -> bool:
    s = get_settings()
    try:
        resp = await _rest("DELETE", f"Recordings/{sid}.json", auth=(s.twilio_api_key_sid or "", s.twilio_api_key_secret or ""))
    except Exception as exc:  # noqa: BLE001 - a failed delete leaves the row `transcribed`, it never fails the job
        log.warning("Twilio recording delete failed: %s", type(exc).__name__)
        return False
    return resp.status_code < 300


@jobs.register("transcribe_handover")
async def transcribe_handover(tenant_id: str, payload: dict[str, Any]) -> None:
    rid = payload["recording_id"]
    try:
        await _run(tenant_id, rid)
    except Exception as exc:
        await _fail_if_last(tenant_id, rid, exc)
        raise


async def _fail_if_last(tenant_id: str, rid: str, exc: Exception) -> None:
    """TEL-23: on the last attempt the row says `failed` with an error; no events were written."""
    async with sessionmaker()() as s:
        job = await s.scalar(select(Job).where(Job.dedupe_key == f"transcribe_handover:{rid}"))
        row = await s.get(CallRecording, rid)
        if row is None or row.tenant_id != tenant_id or row.status != "received":
            return
        if job is None or job.attempts + 1 >= jobs.MAX_ATTEMPTS:
            row.status, row.error = "failed", _scrub(f"{type(exc).__name__}: {exc}")
            await s.commit()


async def _run(tenant_id: str, rid: str) -> None:
    async with sessionmaker()() as s:
        row = await s.get(CallRecording, rid)
        if row is None or row.tenant_id != tenant_id or row.status != "received":  # idempotent: done, failed or deleted
            return
        call = await s.get(Call, row.call_id)
        if call is None:
            return
        version = await s.get(AgentVersion, call.agent_version_id)
        languages = list(((version.config if version else None) or {}).get("languages") or [])
        sid, channels, cmap = row.recording_sid, row.channels, dict(row.channel_map or {})
        started = row.created_at - timedelta(seconds=row.duration_s or 0)
    transcriber = transcribe.get_transcriber()
    if transcriber is None:
        raise RuntimeError("no transcriber configured (HANDOVER_STT_PROVIDER / DEEPGRAM_API_KEY)")
    wav = await _download(sid, channels)
    parts = transcribe.split_channels(wav)
    mono = len(parts) == 1
    lines: list[tuple[float, float, str, str, str | None]] = []  # (start, end, speaker, text, language)
    for index, audio in enumerate(parts, start=1):
        speaker = "mixed" if mono else cmap.get(str(index), "caller" if index == 1 else "specialist")
        for seg in await transcriber.transcribe(audio, languages):
            lines.append((seg.start_s, seg.end_s, speaker, seg.text, seg.language))
    lines.sort(key=lambda x: (x[0], x[1]))
    async with sessionmaker()() as s:
        row = await s.get(CallRecording, rid)
        if row is None or row.status != "received":
            return
        call = await s.get(Call, row.call_id)
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == row.call_id))
        author = (esc.assignee if esc and esc.assignee else None) or "Specialist"
        if mono:
            await add_event(s, call, "system", "recording_mono", {"event": "recording_mono", "recording_id": rid}, at=started)
        for start_s, end_s, speaker, text, language in lines:
            data: dict[str, Any] = {"on_human_leg": True, "start_s": start_s, "end_s": end_s, "language": language, "recording_id": rid}
            at = started + timedelta(seconds=start_s)
            if speaker == "caller":
                await add_event(s, call, "user", text, data, at=at)
            else:
                data["author"] = author
                if speaker == "mixed":
                    data["speaker"] = "mixed"
                await add_event(s, call, "human", text, data, at=at)
        row.status, row.transcribed_at, row.error = "transcribed", utcnow(), None
        await s.commit()
        call_id = call.id
    if get_settings().twilio_recording_delete and await _delete(sid):
        async with sessionmaker()() as s:
            row = await s.get(CallRecording, rid)
            if row is not None:
                row.status, row.deleted_at = "deleted", utcnow()
                await s.commit()
    bus.publish(tenant_id, "console", "handover.transcribed", {"call_id": call_id, "recording_id": rid})
    await _requeue_learning(tenant_id, call_id)


async def _requeue_learning(tenant_id: str, call_id: str) -> None:
    """TEL-24: the call is analysed again so the analysis sees what the person said (the existing re-analysis key)."""
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        if call is None or call.is_eval or call.ended_at is None:
            return
        await jobs.enqueue(s, tenant_id, "analyze_call", {"call_id": call_id}, dedupe_key=f"analyze_call:{call_id}:2")
        await s.commit()


def human_portion(events: list[CallEvent], limit: int = 600) -> str:
    """The specialist's transcribed lines joined, cut at `limit` characters (the fix drafter's evidence)."""
    text = " ".join(e.text or "" for e in events if e.kind == "human" and (e.data or {}).get("on_human_leg") and e.text).strip()
    return text[:limit]

