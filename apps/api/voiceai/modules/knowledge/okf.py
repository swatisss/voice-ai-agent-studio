"""Open Knowledge Format (OKF) bundle reading: frontmatter parsing and bundle import.

Spec: /architecture/knowledge.md (Sources: okf), /decisions/adr-0001-spec-driven-okf.md
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

RESERVED = {"index.md", "log.md"}


@dataclass
class OkfConcept:
    path: str
    title: str
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return None, text
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return None, text
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return (meta if isinstance(meta, dict) else None), body


def _concept(path: str, text: str) -> OkfConcept | None:
    if PurePosixPath(path).name in RESERVED:
        return None
    meta, body = split_frontmatter(text)
    if not meta or not meta.get("type"):
        return None
    title = str(meta.get("title") or PurePosixPath(path).stem.replace("-", " ").capitalize())
    keep = {k: meta[k] for k in ("type", "description", "tags", "resource", "status") if k in meta}
    keep["okf_path"] = path
    return OkfConcept(path=path, title=title, content=body.strip(), meta=keep)


def read_zip(data: bytes) -> list[OkfConcept]:
    out: list[OkfConcept] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith(".md") or name.startswith("__MACOSX"):
                continue
            c = _concept(name, zf.read(name).decode("utf-8", errors="replace"))
            if c:
                out.append(c)
    return out


def read_dir(root: Path) -> list[OkfConcept]:
    out: list[OkfConcept] = []
    for p in sorted(root.rglob("*.md")):
        c = _concept(p.relative_to(root).as_posix(), p.read_text(encoding="utf-8"))
        if c:
            out.append(c)
    return out
