#!/usr/bin/env python3
"""Spec bundle checks for spec-driven development.

Spec: /process/sdd-workflow.md (Guardrails), /process/conventions.md

Checks (stdlib only, so it runs in git hooks and CI without a venv):
  * OKF lint: frontmatter + non-empty `type` on every concept; reserved index.md/log.md rules
  * repo rules: `title`, `description`, `status` on every concept
  * index coverage: every concept and subfolder is listed in its folder's index.md
  * links: relative and bundle-absolute links resolve
  * acceptance IDs: unique; tests may only cite IDs that exist (SDD-08)
  * spec-first rule: --commit-msg-file (commit hook) and --base (whole PR) (SDD-01)
  * log rule, lifecycle rule: --base (SDD-05, SDD-06)
  * coverage ratchet: --ci (SDD-07)

Exit code 0 = ok, 1 = errors.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
BASELINE = ROOT / "scripts" / "acceptance-baseline.txt"
RESERVED = {"index.md", "log.md"}
REPO_REQUIRED = ("title", "description", "status")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
ACCEPT_RE = re.compile(r"^\s*-\s+\*\*(?:~~)?([A-Z]{2,5}-\d{2,3})(?:~~)?\*\*")
COVERS_RE = re.compile(r"\b([A-Z]{2,5}-\d{2,3})\b")
CODE_DIRS = ("apps/api/tests", "apps/web")
LOCK_FILES = {"apps/api/uv.lock", "apps/web/package-lock.json"}
TEST_PREFIX = "apps/api/tests/"


def is_behavior_path(path: str) -> bool:
    """Code whose change can alter behavior: apps/ minus tests and lock files (SDD-01)."""
    return path.startswith("apps/") and not path.startswith(TEST_PREFIX) and path not in LOCK_FILES


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code so examples are not linted."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return top-level frontmatter keys -> raw values, or None if absent."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fields


def frontmatter_yaml_problems(text: str) -> list[str]:
    """Plain (unquoted) scalars containing ': ' are invalid YAML; the OKF importer would skip such a file."""
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return []
    problems = []
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s+(.*)$", line)
        if m and ": " in m.group(2) and not m.group(2).lstrip().startswith(('"', "'", "{", "[", "|", ">")):
            problems.append(m.group(1))
    return problems


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def lint_files(rep: Report) -> list[Path]:
    md_files = sorted(SPECS.rglob("*.md"))
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if f.name in RESERVED:
            if f.name == "index.md" and fm is not None:
                if f.parent != SPECS or set(fm) - {"okf_version"}:
                    rep.err(f"{rel(f)}: index.md may only carry frontmatter at the bundle root (okf_version)")
            if f.name == "log.md" and fm is not None:
                rep.err(f"{rel(f)}: log.md must not have frontmatter")
            continue
        if fm is None:
            rep.err(f"{rel(f)}: missing YAML frontmatter (OKF requires it)")
            continue
        if not fm.get("type"):
            rep.err(f"{rel(f)}: frontmatter has no non-empty `type`")
        for key in frontmatter_yaml_problems(text):
            rep.err(f"{rel(f)}: frontmatter `{key}` contains ': ' and must be quoted (invalid YAML otherwise)")
        for key in REPO_REQUIRED:
            if not fm.get(key):
                rep.err(f"{rel(f)}: frontmatter missing `{key}` (repo rule)")
        if fm.get("status") and fm["status"] not in ("draft", "stable", "deprecated"):
            rep.err(f"{rel(f)}: status must be draft|stable|deprecated")
    return md_files


def check_indexes(rep: Report) -> None:
    for folder in sorted([SPECS, *[d for d in SPECS.rglob("*") if d.is_dir()]]):
        concepts = [p for p in folder.glob("*.md") if p.name not in RESERVED]
        subdirs = [d for d in folder.iterdir() if d.is_dir() and any(d.rglob("*.md"))]
        if not concepts and not subdirs:
            continue
        index = folder / "index.md"
        if not index.exists():
            rep.err(f"{rel(folder)}/: missing index.md")
            continue
        targets = {t.split("#")[0].rstrip("/") for t in LINK_RE.findall(strip_code(index.read_text(encoding="utf-8")))}
        for c in concepts:
            if c.name not in targets:
                rep.err(f"{rel(index)}: does not list {c.name}")
        for d in subdirs:
            if d.name not in targets:
                rep.err(f"{rel(index)}: does not list subfolder {d.name}/")


def check_links(rep: Report, files: list[Path]) -> None:
    for f in files:
        body = strip_code(f.read_text(encoding="utf-8"))
        for target in LINK_RE.findall(body):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#")[0]
            if not path:
                continue
            resolved = (SPECS / path.lstrip("/")) if path.startswith("/") else (f.parent / path)
            resolved = resolved.resolve()
            if not resolved.exists():
                rep.err(f"{rel(f)}: broken link -> {target}")


def collect_acceptance(rep: Report, files: list[Path]) -> dict[str, tuple[str, str]]:
    """Acceptance ID -> (location, status of the declaring spec)."""
    seen: dict[str, tuple[str, str]] = {}
    for f in files:
        text = f.read_text(encoding="utf-8")
        status = (parse_frontmatter(text) or {}).get("status", "stable")
        in_fence = False
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence:
                continue
            m = ACCEPT_RE.match(line)
            if not m:
                continue
            ident, loc = m.group(1), f"{rel(f)}:{i}"
            if ident in seen:
                rep.err(f"duplicate acceptance ID {ident}: {seen[ident][0]} and {loc}")
            else:
                seen[ident] = (loc, status)
    return seen


def cited_ids() -> set[str]:
    cited: set[str] = set()
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".ts", ".tsx"} and "node_modules" not in p.parts:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "Covers:" in line:
                        cited.update(COVERS_RE.findall(line))
    return cited


def read_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def check_coverage(rep: Report, ids: dict[str, tuple[str, str]], ratchet: bool, baseline: set[str]) -> tuple[int, int]:
    cited = cited_ids()
    unknown = sorted(cited - set(ids))
    if unknown:  # SDD-08
        rep.err(f"tests cite acceptance IDs that no spec defines: {', '.join(unknown)}")
    uncited = sorted(set(ids) - cited)
    if not ratchet:
        if uncited:
            rep.warn(f"{len(uncited)} acceptance IDs not cited by any test: {', '.join(uncited)}")
    else:
        counted = [i for i in uncited if ids[i][1] == "stable"]  # draft specs are not implemented yet
        fresh = [i for i in counted if i not in baseline]
        if fresh:  # SDD-07
            rep.err(
                "stable acceptance IDs with no test (add a test with `Covers: ID`, or mark the spec draft until implemented): "
                + ", ".join(f"{i} ({ids[i][0]})" for i in fresh)
            )
        stale = sorted(b for b in baseline if b in cited or b not in ids)
        if stale:
            rep.err(f"scripts/acceptance-baseline.txt lists IDs that now have tests or no longer exist - remove them: {', '.join(stale)}")
        manual = len([b for b in baseline if b in ids and b not in cited])
        if manual:
            rep.warn(f"{manual} acceptance IDs are verified by hand (scripts/acceptance-baseline.txt)")
    return len(ids) - len(uncited), len(ids)


def check_spec_first(rep: Report, msg_file: str) -> None:
    """Commit-msg hook: behavior code staged without a spec change needs [no-spec] (SDD-01)."""
    message = Path(msg_file).read_text(encoding="utf-8", errors="ignore")
    if "[no-spec]" in message:
        return
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line]
    if any(is_behavior_path(p) for p in staged) and not any(p.startswith("specs/") for p in staged):
        rep.err(
            "spec-first rule: this commit changes behavior code under apps/ but not specs/. "
            "Update the governing spec (and specs/log.md), or add [no-spec] to the message "
            "if this does not change behavior. See specs/process/sdd-workflow.md"
        )


def check_pr(rep: Report, base: str) -> None:
    """CI: spec-first, log and lifecycle rules over the whole PR range (SDD-01, SDD-05, SDD-06)."""
    changed = [p for p in git("diff", "--name-only", f"{base}...HEAD").splitlines() if p]
    code = [p for p in changed if is_behavior_path(p)]
    specs = [p for p in changed if p.startswith("specs/")]
    messages = git("log", "--format=%B", f"{base}..HEAD")
    exempt = "[no-spec]" in messages or os.environ.get("SPEC_EXEMPT", "").lower() in ("1", "true")

    if code and not specs and not exempt:
        rep.err(
            f"spec-first rule: this PR changes behavior code ({code[0]}{' and others' if len(code) > 1 else ''}) but nothing under specs/. "
            "Update the governing spec, or add [no-spec] to a commit message / the `no-spec` PR label if behavior is unchanged."
        )
    spec_docs = [p for p in specs if p.endswith(".md") and p != "specs/log.md"]
    if spec_docs and "specs/log.md" not in changed:
        rep.err(f"log rule: spec files changed ({spec_docs[0]}{' and others' if len(spec_docs) > 1 else ''}) but specs/log.md has no new entry.")
    if code:
        for p in spec_docs:
            path = ROOT / p
            if not path.exists():
                continue
            fm = parse_frontmatter(path.read_text(encoding="utf-8")) or {}
            if fm.get("status") == "draft":
                rep.err(f"lifecycle rule: {p} is status: draft but this PR also changes code. Mark it stable once implemented.")
            if fm.get("cp_state") == "proposed":
                rep.err(f"lifecycle rule: {p} is cp_state: proposed but this PR also changes code. Get it accepted first.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit-msg-file", help="run the spec-first rule against a commit message file (git hook)")
    ap.add_argument("--skip-lint", action="store_true", help="only run the spec-first rule")
    ap.add_argument("--ci", action="store_true", help="CI mode: enforce the stable-spec acceptance coverage ratchet")
    ap.add_argument("--base", help="git ref to diff against (e.g. origin/main): PR-level spec-first, log and lifecycle rules")
    ap.add_argument("--baseline", type=Path, default=BASELINE, help="acceptance IDs verified by hand (default: scripts/acceptance-baseline.txt)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rep = Report()
    covered = total = 0
    if not args.skip_lint:
        files = lint_files(rep)
        check_indexes(rep)
        check_links(rep, files)
        ids = collect_acceptance(rep, files)
        covered, total = check_coverage(rep, ids, args.ci, read_baseline(args.baseline))
    if args.commit_msg_file:
        check_spec_first(rep, args.commit_msg_file)
    if args.base:
        try:
            check_pr(rep, args.base)
        except RuntimeError as exc:
            rep.err(f"could not compare against {args.base}: {exc} (CI needs `fetch-depth: 0`)")

    for w in rep.warnings:
        if not args.quiet:
            print(f"warning: {w}")
    for e in rep.errors:
        print(f"error: {e}")
    if not args.skip_lint and not args.quiet:
        print(f"spec_check: {len(rep.errors)} error(s); acceptance coverage {covered}/{total}")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
