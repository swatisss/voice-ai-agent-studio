"""Test fixtures: temp SQLite, hash embedder, fake LLM, seeded demo data, in-process HTTP client."""
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="voiceai-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
    "EMBEDDINGS_PROVIDER": "hash",
    "AUTO_SEED": "0",
    "JOBS_ENABLED": "0",
    "LLM_FAKE": "1",
    "GROQ_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "OPENAI_API_KEY": "",
    "DEEPGRAM_API_KEY": "",
    "WEB_DIST_DIR": str(_TMP / "no-web"),
})

import httpx  # noqa: E402
import pytest  # noqa: E402

from voiceai import db  # noqa: E402
from voiceai.config import get_settings  # noqa: E402
from voiceai.llm import gateway as gw  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_business_data() -> None:
    """Mock business records are module state (policies, onboarding, requests): start every test from the seed state."""
    from voiceai.mock import data

    data.reset()


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[None]:
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    await db.init_db()
    from voiceai.knowledge.search import invalidate
    from voiceai.runtime.session import REGISTRY

    invalidate()
    REGISTRY.clear()
    yield
    from voiceai.runtime.escalation import wait_packets

    await wait_packets()
    gw.set_fake(None)
    await db.engine().dispose()


@pytest.fixture
async def seeded(database: None) -> dict[str, Any]:
    from voiceai.seed.loader import seed

    return await seed()


@pytest.fixture
def app():  # noqa: ANN201
    from voiceai.main import app as fastapi_app
    from voiceai.runtime import app_ref

    app_ref.APP = fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app, database) -> AsyncIterator[httpx.AsyncClient]:  # noqa: ANN001
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def members_headers() -> dict[str, str]:
    return {"X-Tenant-Id": "evergreen-care"}


Responder = Callable[[str, list[dict[str, Any]], Any], Any]


@pytest.fixture
def fake_llm() -> Callable[[Responder], None]:
    def install(responder: Responder) -> None:
        gw.set_fake(responder)

    yield install
    gw.set_fake(None)


def script(*replies: Any) -> Responder:
    """Realtime replies in order; other roles return None unless given as {role: value} dict entries."""
    queue = list(replies)

    def responder(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:
        if role != "realtime":
            raise RuntimeError(f"unexpected role {role}")
        return queue.pop(0) if queue else gw.FakeReply(text="Okay.")

    return responder
