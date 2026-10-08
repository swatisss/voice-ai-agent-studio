"""Knowledge ingestion and search. Covers: KN-01, KN-02, KN-03, KN-04, KN-05, KN-06"""
from __future__ import annotations

import io
import zipfile

from voiceai.core.db import sessionmaker
from voiceai.modules.knowledge import okf
from voiceai.modules.knowledge.chunking import MAX_CHARS, chunk_markdown
from voiceai.modules.knowledge.service import create_doc
from voiceai.modules.knowledge.search import search
from voiceai.core.tables import Tenant


def test_heading_chunks():
    """Covers: KN-01"""
    md = "## Claims\nPaid claims are explained on the EOB statement.\n## Appeals\nYou can appeal within 180 days of a denial.\n## Cards\nDigital cards are available in the app right away."
    chunks = chunk_markdown(md)
    assert [c.heading for c in chunks] == ["Claims", "Appeals", "Cards"]


def test_long_sections_split_with_overlap():
    """Covers: KN-02"""
    para = "Sentence about coverage rules and plan details. " * 8
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
        d1 = await create_doc(s, "t1", "ID cards", "## Replacement\nReplacement ID cards arrive by mail in 7 to 10 business days.", "text")
        d2 = await create_doc(s, "t1", "Telehealth", "## Video visits\nTelehealth video visits cost zero dollars on silver plans.", "text")
        await s.commit()
        hit = await search(s, "t1", [d1.id], "replacement id card mail")
        assert hit["results"][0]["doc_id"] == d1.id
        scoped = await search(s, "t1", [d1.id], "telehealth video visits cost")
        assert all(r["doc_id"] != d2.id for r in scoped.get("results", []))
        miss = await search(s, "t1", [d1.id, d2.id], "quantum chromodynamics lattice gauge")
        assert miss.get("no_answer") is True


async def test_draft_doc_only_when_listed(database):
    """Covers: KN-06"""
    async with sessionmaker()() as s:
        await _tenant(s)
        active = await create_doc(s, "t1", "Cards", "## Cards\nDigital ID cards are in the app.", "text")
        draft = await create_doc(s, "t1", "Newborns", "## Newborns\nAdd a newborn within 60 days of birth.", "proposal", status="draft")
        await s.commit()
        published = await search(s, "t1", [active.id], "add newborn within 60 days")
        assert all(r["doc_id"] != draft.id for r in published.get("results", []))
        candidate = await search(s, "t1", [active.id, draft.id], "add newborn within 60 days")
        assert candidate["results"][0]["doc_id"] == draft.id
