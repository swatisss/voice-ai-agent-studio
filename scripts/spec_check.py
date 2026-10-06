#!/usr/bin/env python3
"""Spec bundle checks for spec-driven development.

Spec: /process/sdd-workflow.md (Guardrails), /process/conventions.md

Checks (stdlib only, so it runs in git hooks without a venv):
  * OKF lint: frontmatter + non-empty `type` on every concept; reserved index.md/log.md rules
  * repo rules: `title`, `description`, `status` on every concept
  * index coverage: every concept and subfolder is listed in its folder's index.md
  * links: relative and bundle-absolute links resolve
  * acceptance IDs: unique; uncited IDs reported as warnings
  * spec-first rule (--commit-msg-file): commits touching apps/ must touch specs/ or say [no-spec]

Exit code 0 = ok, 1 = errors.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
RESERVED = {"index.md", "log.md"}
REPO_REQUIRED = ("title", "description", "status")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
ACCEPT_RE = re.compile(r"^\s*-\s+\*\*(?:~~)?([A-Z]{2,5}-\d{2,3})(?:~~)?\*\*")
COVERS_RE = re.compile(r"\b([A-Z]{2,5}-\d{2,3})\b")
CODE_DIRS = ("apps/api/tests", "apps/web")


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


def collect_acceptance(rep: Report, files: list[Path]) -> dict[str, str]:
    seen: dict[str, str] = {}
    for f in files:
        in_fence = False
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if in_fence:
                continue
            m = ACCEPT_RE.match(line)
            if not m:
                continue
            ident, loc = m.group(1), f"{rel(f)}:{i}"
            if ident in seen:
                rep.err(f"duplicate acceptance ID {ident}: {seen[ident]} and {loc}")
            else:
                seen[ident] = loc
    return seen


def check_coverage(rep: Report, ids: dict[str, str]) -> tuple[int, int]:
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
    uncited = sorted(set(ids) - cited)
    if uncited:
        rep.warn(f"{len(uncited)} acceptance IDs not cited by any test: {', '.join(uncited)}")
    return len(ids) - len(uncited), len(ids)


def check_spec_first(rep: Report, msg_file: str) -> None:
    message = Path(msg_file).read_text(encoding="utf-8", errors="ignore")
    if "[no-spec]" in message:
        return
    out = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, capture_output=True, text=True)
    staged = [line for line in out.stdout.splitlines() if line]
    touches_apps = any(p.startswith("apps/") for p in staged)
    touches_specs = any(p.startswith("specs/") for p in staged)
    if touches_apps and not touches_specs:
        rep.err(
            "spec-first rule: this commit changes apps/ but not specs/. "
            "Update the governing spec (and specs/log.md), or add [no-spec] to the message "
            "if this does not change behavior. See specs/process/sdd-workflow.md"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit-msg-file", help="run the spec-first rule against a commit message file")
    ap.add_argument("--skip-lint", action="store_true", help="only run the spec-first rule")
    ap.add_argument("--strict-coverage", action="store_true", help="treat uncited acceptance IDs as errors")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rep = Report()
    covered = total = 0
    if not args.skip_lint:
        files = lint_files(rep)
        check_indexes(rep)
        check_links(rep, files)
        ids = collect_acceptance(rep, files)
        covered, total = check_coverage(rep, ids)
        if args.strict_coverage and rep.warnings:
            rep.errors.extend(rep.warnings)
    if args.commit_msg_file:
        check_spec_first(rep, args.commit_msg_file)

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
