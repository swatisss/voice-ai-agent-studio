"""Heading-aware Markdown chunking.

Spec: /architecture/knowledge.md (Chunking)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 900
OVERLAP = 120
MIN_CHARS = 40
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")


@dataclass
class Chunk:
    heading: str
    content: str


def _sections(text: str) -> list[tuple[str, str]]:
    path: list[tuple[int, str]] = []
    heading = ""
    body: list[str] = []
    out: list[tuple[str, str]] = []
    in_fence = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            out.append((heading, content))

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            body = []
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
            heading = " > ".join(t for _, t in path)
        else:
            body.append(line)
    flush()
    return out


def _hard_split(paragraph: str, limit: int) -> list[str]:
    pieces: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    buf = ""
    for s in sentences:
        while len(s) > limit:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(s[:limit])
            s = s[limit:]
        if len(buf) + len(s) + 1 > limit and buf:
            pieces.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def _split_long(content: str) -> list[str]:
    if len(content) <= MAX_CHARS:
        return [content]
    budget = MAX_CHARS - OVERLAP - 2
    paragraphs: list[str] = []
    for p in re.split(r"\n\s*\n", content):
        p = p.strip()
        if p:
            paragraphs.extend(_hard_split(p, budget) if len(p) > budget else [p])
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        candidate = f"{buf}\n\n{p}" if buf else p
        if len(candidate) <= MAX_CHARS:
            buf = candidate
            continue
        chunks.append(buf)
        tail = buf[-OVERLAP:]
        buf = f"{tail}\n\n{p}"
    if buf:
        chunks.append(buf)
    return chunks


def chunk_markdown(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, content in _sections(text):
        for piece in _split_long(content):
            if chunks and len(piece) < MIN_CHARS and len(chunks[-1].content) + len(piece) + 1 <= MAX_CHARS:
                chunks[-1].content += "\n" + piece
            else:
                chunks.append(Chunk(heading, piece))
    return chunks
