"""Knowledge ingestion and search. Covers: KN-01, KN-02, KN-03, KN-04, KN-05, KN-06, KN-08"""
from __future__ import annotations

import io
import json
import zipfile

from voiceai.db import sessionmaker
from voiceai.knowledge import okf
from voiceai.knowledge.chunking import MAX_CHARS, chunk_markdown
from voiceai.knowledge.ingest import create_doc
from voiceai.knowledge.search import search
from voiceai.llm.gateway import FakeReply
from voiceai.models import Tenant


def test_heading_chunks():
    """Covers: KN-01"""
    md = "## Claims\nPaid claims are explained in your claim statement.\n## Appeals\nYou can complain within 6 months of a decision.\n## Cards\nDigital membership cards are available in the app straight away."
    chunks = chunk_markdown(md)
    assert [c.heading for c in chunks] == ["Claims", "Appeals", "Cards"]


def test_long_sections_split_with_overlap():
    """Covers: KN-02"""
    para = "Sentence about cover rules and policy details. " * 8
    md = "## Long\n" + "\n\n".join([para] * 6)
    chunks = chunk_markdown(md)
    assert len(chunks) > 1
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    assert chunks[0].content[-60:] in chunks[1].content


def test_okf_zip_import_skips_reserved_and_strips_frontmatter():
    """Covers: KN-03"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bundle/index.md", "# Index\n* [A](a.md)")
        zf.writestr("bundle/log.md", "# Log")
        zf.writestr("bundle/a.md", "---\ntype: Knowledge Article\ntitle: Alpha\n---\n# Alpha\nBody A")
        zf.writestr("bundle/b.md", "---\ntype: Knowledge Article\ntitle: Beta\n---\nBody B")
    concepts = okf.read_zip(buf.getvalue())
    assert [c.title for c in concepts] == ["Alpha", "Beta"]
    assert all("type:" not in c.content for c in concepts)


async def _tenant(s) -> None:  # noqa: ANN001
    s.add(Tenant(id="t1", name="T1"))
    await s.flush()


async def test_search_no_answer_and_doc_scoping(database):
    """Covers: KN-04, KN-05"""
    async with sessionmaker()() as s:
        await _tenant(s)
        d1 = await create_doc(s, "t1", "ID cards", "## Replacement\nReplacement ID cards arrive by post in 7 to 10 working days.", "text")
        d2 = await create_doc(s, "t1", "Digital GP", "## Video appointments\nDigital GP video appointments cost nothing on every health policy.", "text")
        await s.commit()
        hit = await search(s, "t1", [d1.id], "replacement id card post")
        assert hit["results"][0]["doc_id"] == d1.id
        scoped = await search(s, "t1", [d1.id], "digital gp video appointments cost")
        assert all(r["doc_id"] != d2.id for r in scoped.get("results", []))
        miss = await search(s, "t1", [d1.id, d2.id], "quantum chromodynamics lattice gauge")
        assert miss.get("no_answer") is True


async def test_draft_doc_only_when_listed(database):
    """Covers: KN-06"""
    async with sessionmaker()() as s:
        await _tenant(s)
        active = await create_doc(s, "t1", "Cards", "## Cards\nDigital membership cards are in the app.", "text")
        draft = await create_doc(s, "t1", "Newborns", "## Newborns\nAdd a newborn within 3 months of birth.", "proposal", status="draft")
        await s.commit()
        published = await search(s, "t1", [active.id], "add newborn within 3 months")
        assert all(r["doc_id"] != draft.id for r in published.get("results", []))
        candidate = await search(s, "t1", [active.id, draft.id], "add newborn within 3 months")
        assert candidate["results"][0]["doc_id"] == draft.id


LAST = "Treatment for a condition you had in the five years before joining is excluded under moratorium."
QUERY = "Northgate Complete covers inpatient and day-patient treatment, outpatient consultations and diagnostic tests"  # the hash embedder needs shared words
FILLER = "Northgate Complete covers inpatient and day-patient treatment, outpatient consultations and diagnostic tests for eligible conditions. "


def _policy_880() -> str:
    """One paragraph of exactly 880 characters whose last sentence holds the fact (a single chunk, KN-08)."""
    content = (FILLER * 8)[: 880 - len(LAST) - 1] + " " + LAST
    assert len(content) == 880
    return content


async def test_search_returns_the_whole_chunk(database):
    """Covers: KN-08"""
    content = _policy_880()
    assert len(chunk_markdown(content)) == 1
    async with sessionmaker()() as s:
        await _tenant(s)
        doc = await create_doc(s, "t1", "Northgate Complete policy", content, "text")
        await s.commit()
        result = await search(s, "t1", [doc.id], QUERY)
    top = result["results"][0]
    assert top["content"] == content and top["content"].endswith(LAST)


async def test_model_receives_the_whole_chunk(client, seeded, fake_llm):
    """Covers: KN-08"""
    from tests.test_turn_policy import open_session

    fake_llm(lambda role, messages, tools: FakeReply(text="Okay."))
    async with sessionmaker()() as s:
        doc = await create_doc(s, "northgate-health", "Northgate Complete policy", _policy_880(), "text")
        await s.commit()
    session = await open_session(seeded, channel="text")
    session.tools.knowledge_doc_ids = [doc.id]
    to_model = await session._run_tool("call_1", "search_knowledge", json.dumps({"query": QUERY}))
    assert LAST in to_model and json.loads(to_model)["results"][0]["content"] == _policy_880()
