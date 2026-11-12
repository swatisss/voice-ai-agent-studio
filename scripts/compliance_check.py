#!/usr/bin/env python3
"""Run exactly the tests that prove the healthcare controls and write the compliance report.

Spec: /product/compliance-evidence.md (Status of a control)

    python scripts/compliance_check.py        # writes apps/api/data/compliance-report.json
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "apps" / "api"
SPEC = ROOT / "specs" / "product" / "compliance-evidence.md"
REPORT = API / "data" / "compliance-report.json"
ID = re.compile(r"\b[A-Z]+-\d+\b")


def evidence_ids(spec: Path = SPEC) -> list[str]:
    """Evidence IDs of the Controls table, in order, once each."""
    ids: list[str] = []
    for line in spec.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and re.fullmatch(r"C\d+", cells[0]):
            ids += [i for i in ID.findall(cells[5]) if i not in ids]
    return ids


def _covers(doc: str | None) -> set[str]:
    if not doc or "Covers:" not in doc:
        return set()
    return set(ID.findall(doc[doc.index("Covers:"):]))


def citing_tests(tests_dir: Path = API / "tests") -> dict[str, list[str]]:
    """ID -> test node ids (relative to apps/api); a test's own `Covers:` wins over its module's."""
    found: dict[str, list[str]] = {}
    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _covers(ast.get_docstring(tree))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                for aid in _covers(ast.get_docstring(node)) or module:
                    found.setdefault(aid, []).append(f"tests/{path.name}::{node.name}")
    return found


def run_pytest(nodes: list[str]) -> dict[str, bool]:
    """Node id -> passed."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        subprocess.run(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", *nodes], cwd=API, check=False)
        outcomes: dict[str, bool] = {}
        for case in ET.parse(xml).getroot().iter("testcase"):
            module = case.get("classname", "").replace(".", "/")
            node = f"{module}.py::{case.get('name')}"
            outcomes[node] = not any(child.tag in ("failure", "error") for child in case)
    return outcomes


def build_report(ids: list[str], tests: dict[str, list[str]], runner: Callable[[list[str]], dict[str, bool]] = run_pytest,
                 commit: str = "") -> dict:
    nodes = sorted({n for i in ids for n in tests.get(i, [])})
    outcomes = runner(nodes) if nodes else {}
    out = {}
    for i in ids:
        mine = tests.get(i, [])
        out[i] = {"tests": mine, "failed": sum(1 for n in mine if not outcomes.get(n, False))}
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit, "ids": out}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main() -> int:
    ids = evidence_ids()
    report = build_report(ids, citing_tests(), commit=_commit())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [i for i, r in report["ids"].items() if r["failed"]]
    untested = [i for i, r in report["ids"].items() if not r["tests"]]
    print(f"compliance: {len(ids)} evidence IDs, {len(failed)} failing, {len(untested)} without a test -> {REPORT.relative_to(ROOT)}")
    for i in failed:
        print(f"  FAILED {i}")
    for i in untested:
        print(f"  no test {i}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
