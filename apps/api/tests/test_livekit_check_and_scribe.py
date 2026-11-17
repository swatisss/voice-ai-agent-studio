"""CP-0050: the connectivity check script (against a fake prober) and the scribe's per-track transcriber (against a fake socket).

Covers: LKH-16, LKH-09, LKH-14
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from voiceai import media_room
from voiceai.config import get_settings
from voiceai.voice.scribe import TrackTranscriber

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "livekit_check.py"
SECRET = "lk-secret-0123456789abcdef-never-printed"
VALUES = {"LIVEKIT_URL": "wss://example.livekit.cloud", "LIVEKIT_API_KEY": "APIkeyForTests", "LIVEKIT_API_SECRET": SECRET}


@pytest.fixture
def check(monkeypatch):  # noqa: ANN001, ANN201
    spec = importlib.util.spec_from_file_location("livekit_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    for k in VALUES:
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


class FakeProber:
    def __init__(self, result=None, error: Exception | None = None):  # noqa: ANN001
        self.result, self.error, self.seen = result, error, None

    async def probe(self, url, token, room):  # noqa: ANN001, ANN201
        self.seen = (url, token, room)
        if self.error:
            raise self.error
        return self.result


async def test_check_reports_signalling_media_and_round_trip_without_secrets(check, monkeypatch):
    """Covers: LKH-16"""
    lines: list[str] = []
    prober = FakeProber(check.Probe(True, "udp", 42.0))
    assert await check.run(dict(VALUES), prober, lines.append) == 0
    text = "\n".join(lines)
    assert "signalling: OK" in text and "media path: udp" in text and "round trip: 42 ms" in text
    url, token, room = prober.seen
    assert url == VALUES["LIVEKIT_URL"] and room in text  # a throw-away room
    claims = media_room.decode(token)  # it minted a real token for that room ...
    assert claims["video"]["room"] == room and claims["exp"] - claims["nbf"] <= 120
    assert token not in text and SECRET not in text and VALUES["LIVEKIT_API_KEY"] not in text  # ... and never printed it


async def test_check_exits_non_zero_on_each_failure(check):
    """Covers: LKH-16"""
    lines: list[str] = []
    assert await check.run({**VALUES, "LIVEKIT_API_SECRET": ""}, FakeProber(), lines.append) == 1
    assert "LIVEKIT_API_SECRET" in lines[-1] and SECRET not in "\n".join(lines)
    lines.clear()
    assert await check.run(dict(VALUES), FakeProber(check.Probe(False, error=f"bad key {SECRET}")), lines.append) == 1
    assert "signalling: FAILED" in "\n".join(lines) and SECRET not in "\n".join(lines)
    lines.clear()
    assert await check.run(dict(VALUES), FakeProber(error=RuntimeError(f"boom {SECRET}")), lines.append) == 1
    assert SECRET not in "\n".join(lines)
    lines.clear()
    assert await check.run(dict(VALUES), FakeProber(check.Probe(True, "failed", 10.0)), lines.append) == 1
    assert "no media path" in "\n".join(lines)
    lines.clear()
    assert await check.run(dict(VALUES), FakeProber(check.Probe(True, "relay", None)), lines.append) == 0
    assert "media path: relay" in "\n".join(lines)


def test_check_reads_settings_from_the_environment(check):
    """Covers: LKH-16"""
    assert check.load_env(dict(VALUES)) == VALUES
    assert check.redact(f"x {SECRET} y", VALUES) == "x *** y"


class FakeSocket:
    def __init__(self, messages: list[dict]):
        self.sent: list = []
        self._messages = [json.dumps(m) for m in messages]
        self.closed = False

    async def send(self, data):  # noqa: ANN001, ANN201
        self.sent.append(data)

    async def close(self):  # noqa: ANN201
        self.closed = True

    def __aiter__(self):  # noqa: ANN204
        async def gen():  # noqa: ANN202
            for m in self._messages:
                yield m

        return gen()


def _result(text: str, final: bool, speech_final: bool = False) -> dict:
    return {"type": "Results", "is_final": final, "speech_final": speech_final, "channel": {"alternatives": [{"transcript": text}]}}


async def test_transcriber_turns_deepgram_results_into_partials_and_one_final():
    """Covers: LKH-09"""
    got: list[tuple[str, bool]] = []

    async def on_result(text: str, final: bool) -> None:
        got.append((text, final))

    sock = FakeSocket([_result("I need", False), _result("I need help", True), _result("with my", False),
                       _result("with my claim", True, speech_final=True), _result("", True, True)])

    async def connect(url: str, key: str):  # noqa: ANN202
        assert "linear16" in url and "sample_rate=16000" in url and key == "dg-test"
        return sock

    t = TrackTranscriber("dg-test", on_result, connect=connect)
    await t.start()
    await t.feed(b"\x00\x01" * 160)
    await t._reader  # noqa: SLF001 - the fake socket ends after its messages
    finals = [x for x in got if x[1]]
    assert finals == [("I need help with my claim", True)]
    assert ("I need help with my", False) in got and sock.sent[0] == b"\x00\x01" * 160
    await t.close()
    assert sock.closed
