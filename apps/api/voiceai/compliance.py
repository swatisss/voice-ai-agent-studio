"""Compliance evidence: the controls table read verbatim from the spec, merged with the latest test report.

Spec: /product/compliance-evidence.md
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from voiceai.config import API_DIR, get_settings

REPORT = API_DIR / "data" / "compliance-report.json"
_ID = re.compile(r"\b[A-Z]+-\d+\b")


def _spec() -> str:
    return (get_settings().specs_dir / "product" / "compliance-evidence.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> list[str]:
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("# "):
            inside = line[2:].strip().lower().startswith(heading)
            continue
        if inside:
            lines.append(line)
    return lines


def controls() -> list[dict[str, Any]]:
    """Rows of the Controls table, in spec order."""
    rows = []
    for line in _section(_spec(), "controls"):
        cells = [c.strip().replace("`", "") for c in line.strip().strip("|").split("|")]  # plain text on the page
        if len(cells) != 6 or not re.fullmatch(r"C\d+", cells[0]):
            continue
        rows.append({"id": cells[0], "rule": cells[1], "reference": cells[2], "enforcement": cells[3], "where": cells[4],
                     "evidence_ids": _ID.findall(cells[5])})
    return rows


def gaps() -> list[str]:
    return [line[2:].strip() for line in _section(_spec(), "open gaps") if line.startswith("* ")]


def load_report(path: Path | None = None) -> dict[str, Any] | None:
    try:
        return json.loads((path or REPORT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def evidence(report: dict[str, Any] | None = None) -> dict[str, Any]:
    """CMP-01: every control with the status of each evidence ID and of the control."""
    results = (report or {}).get("ids") or {}
    out = []
    for c in controls():
        items = []
        for aid in c.pop("evidence_ids"):
            r = results.get(aid)
            if r is None:
                status, tests = "not_run", []
            elif not r.get("tests"):
                status, tests = "no_test", []
            else:
                status, tests = ("failed" if r.get("failed") else "passed"), r["tests"]
            items.append({"id": aid, "status": status, "tests": tests})
        if not items:
            status = "process"
        elif any(i["status"] == "failed" for i in items):
            status = "failed"
        elif any(i["status"] == "not_run" for i in items):
            status = "not_run"
        else:
            status = "passed"
        out.append({**c, "status": status, "evidence": items})
    meta = {"generated_at": report.get("generated_at"), "commit": report.get("commit")} if report else None
    return {"controls": out, "gaps": gaps(), "report": meta}
