"""SDD tooling: spec_check.py on synthetic bundles and throwaway git repos.

Covers: SDD-01, SDD-02, SDD-03, SDD-04, SDD-05, SDD-06, SDD-07, SDD-08
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MARK = "Cov" + "ers: "  # built at runtime so this file does not itself cite the fake IDs it writes into fixtures
GIT =["git", "-c", "user.name=tester", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _load(tmp: Path):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("spec_check", REPO / "scripts" / "spec_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.ROOT, mod.SPECS = tmp, tmp / "specs"
    return mod


def _concept(type_: str = "Component Spec", body: str = "", status: str = "stable", extra: str = "") -> str:
    return f"---\ntype: {type_}\ntitle: X\ndescription: Y\nstatus: {status}\n{extra}---\n# Body\n{body}\n"


def _write(tmp: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _bundle(tmp: Path, files: dict[str, str]) -> None:
    _write(tmp, {f"specs/{k}": v for k, v in files.items()})


def _run(mod, ratchet: bool = False, baseline: set[str] | None = None):  # noqa: ANN001, ANN202
    rep = mod.Report()
    files = mod.lint_files(rep)
    mod.check_indexes(rep)
    mod.check_links(rep, files)
    ids = mod.collect_acceptance(rep, files)
    mod.check_coverage(rep, ids, ratchet, baseline or set())
    return rep


def _git(tmp: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=tmp, check=True, capture_output=True)


def _repo(tmp: Path) -> None:
    """A repo whose `main` already contains an index and a log."""
    _git(tmp, "init", "-q", "-b", "main")
    _bundle(tmp, {"index.md": "* [a](a.md) - a\n", "log.md": "# Log\n", "a.md": _concept()})
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "base")
    _git(tmp, "checkout", "-q", "-b", "feature")


def _commit(tmp: Path, message: str = "change") -> None:
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", message)


def _pr(tmp: Path, monkeypatch: pytest.MonkeyPatch | None = None):  # noqa: ANN202
    mod = _load(tmp)
    rep = mod.Report()
    mod.check_pr(rep, "main")
    return rep


# ---------------------------------------------------------------- bundle lint
def test_missing_type_fails(tmp_path):
    """Covers: SDD-02"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": "# no frontmatter\n"})
    assert any("missing YAML frontmatter" in e for e in _run(_load(tmp_path)).errors)


def test_unquoted_colon_in_frontmatter_fails(tmp_path):
    """Covers: SDD-02"""
    bad = "---\ntype: Knowledge Article\ntitle: X\ndescription: How it works: the steps\nstatus: stable\n---\n# Body\n"
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": bad})
    assert any("must be quoted" in e for e in _run(_load(tmp_path)).errors)
    _bundle(tmp_path, {"a.md": bad.replace("How it works: the steps", '"How it works: the steps"')})
    assert not any("must be quoted" in e for e in _run(_load(tmp_path)).errors)


def test_duplicate_acceptance_ids_fail(tmp_path):
    """Covers: SDD-03"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n* [b](b.md) - b\n",
                       "a.md": _concept(body="- **ES-01** — Given x, then y."), "b.md": _concept(body="- **ES-01** — Given z, then w.")})
    assert any("duplicate acceptance ID ES-01" in e for e in _run(_load(tmp_path)).errors)


def test_index_must_list_concepts(tmp_path):
    """Covers: SDD-04"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": _concept(), "b.md": _concept()})
    assert any("does not list b.md" in e for e in _run(_load(tmp_path)).errors)


# ---------------------------------------------------------------- spec-first (commit hook)
def test_spec_first_commit_hook(tmp_path):
    """Covers: SDD-01"""
    _git(tmp_path, "init", "-q", "-b", "main")
    mod = _load(tmp_path)
    msg = tmp_path / "MSG"

    def stage(path: str) -> None:
        _write(tmp_path, {path: "print(1)\n"})
        _git(tmp_path, "add", path)

    stage("apps/api/voiceai/x.py")
    msg.write_text("Change behavior")
    rep = mod.Report()
    mod.check_spec_first(rep, str(msg))
    assert rep.errors and "spec-first rule" in rep.errors[0]
    msg.write_text("Refactor only [no-spec]")
    rep = mod.Report()
    mod.check_spec_first(rep, str(msg))
    assert not rep.errors
    _git(tmp_path, "reset", "-q")  # tests and lock files alone never need a spec change
    stage("apps/api/tests/test_x.py")
    stage("apps/api/uv.lock")
    msg.write_text("Add a test")
    rep = mod.Report()
    mod.check_spec_first(rep, str(msg))
    assert not rep.errors


# ---------------------------------------------------------------- PR-level rules
def test_pr_spec_first(tmp_path, monkeypatch):
    """Covers: SDD-01"""
    monkeypatch.delenv("SPEC_EXEMPT", raising=False)
    _repo(tmp_path)
    _write(tmp_path, {"apps/api/voiceai/x.py": "print(1)\n"})
    _commit(tmp_path, "code only")
    assert any("spec-first rule" in e for e in _pr(tmp_path).errors)
    # exemption 1: [no-spec] in any commit message of the PR
    _write(tmp_path, {"apps/api/voiceai/y.py": "print(2)\n"})
    _commit(tmp_path, "refactor [no-spec]")
    assert not _pr(tmp_path).errors
    # exemption 2: the CI label, passed as SPEC_EXEMPT
    _git(tmp_path, "reset", "-q", "--hard", "main")
    _write(tmp_path, {"apps/api/voiceai/x.py": "print(1)\n"})
    _commit(tmp_path, "code only")
    monkeypatch.setenv("SPEC_EXEMPT", "true")
    assert not _pr(tmp_path).errors


def test_pr_log_rule(tmp_path, monkeypatch):
    """Covers: SDD-05"""
    monkeypatch.delenv("SPEC_EXEMPT", raising=False)
    _repo(tmp_path)
    _bundle(tmp_path, {"a.md": _concept(body="changed")})
    _commit(tmp_path, "edit spec")
    errors = _pr(tmp_path).errors
    assert any("log rule" in e and "specs/log.md" in e for e in errors)
    _bundle(tmp_path, {"log.md": "# Log\n## 2026-10-06\n* **Update**: a\n"})
    _commit(tmp_path, "log it")
    assert not _pr(tmp_path).errors


def test_pr_lifecycle_rule(tmp_path, monkeypatch):
    """Covers: SDD-06"""
    monkeypatch.delenv("SPEC_EXEMPT", raising=False)
    _repo(tmp_path)
    _bundle(tmp_path, {"a.md": _concept(status="draft"), "log.md": "# Log\n* x\n"})
    _write(tmp_path, {"apps/api/voiceai/x.py": "print(1)\n"})
    _commit(tmp_path, "code against draft")
    errors = _pr(tmp_path).errors
    assert any("lifecycle rule" in e and "specs/a.md" in e and "draft" in e for e in errors)
    _bundle(tmp_path, {"a.md": _concept(status="stable")})
    _commit(tmp_path, "mark stable")
    assert not _pr(tmp_path).errors
    # a proposed change proposal may not ship with code either
    _bundle(tmp_path, {"cp.md": _concept("Change Proposal", extra="cp_state: proposed\n")})
    _commit(tmp_path, "proposal")
    assert any("cp_state: proposed" in e for e in _pr(tmp_path).errors)
    # but a spec-only PR (no code) may carry drafts and proposals
    _git(tmp_path, "reset", "-q", "--hard", "main")
    _bundle(tmp_path, {"a.md": _concept(status="draft"), "log.md": "# Log\n* x\n"})
    _commit(tmp_path, "spec-only draft")
    assert not _pr(tmp_path).errors


# ---------------------------------------------------------------- acceptance coverage
def test_ratchet_stable_vs_draft_and_baseline(tmp_path):
    """Covers: SDD-07"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n* [b](b.md) - b\n", "log.md": "# Log\n",
                       "a.md": _concept(body="- **ZZ-01** — Given x, then y."),
                       "b.md": _concept(body="- **ZZ-02** — Given x, then y.", status="draft")})
    mod = _load(tmp_path)
    errors = _run(mod, ratchet=True).errors
    assert any("ZZ-01" in e for e in errors) and not any("ZZ-02" in e for e in errors)   # draft is exempt
    assert not _run(mod, ratchet=True, baseline={"ZZ-01"}).errors                        # baseline = known manual gap
    assert not [e for e in _run(mod, ratchet=False).errors if "ZZ" in e]                 # advisory outside CI
    _write(tmp_path, {"apps/api/tests/test_zz.py": f'"""{MARK}ZZ-01"""\n'})
    assert not _run(mod, ratchet=True).errors                                           # a test satisfies it
    assert any("remove them" in e and "ZZ-01" in e for e in _run(mod, ratchet=True, baseline={"ZZ-01"}).errors)  # stale baseline


def test_tests_may_only_cite_existing_ids(tmp_path):
    """Covers: SDD-08"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": _concept(body="- **ZZ-01** — Given x, then y.")})
    _write(tmp_path, {"apps/api/tests/test_zz.py": f'"""{MARK}ZZ-01, ZZ-99"""\n'})
    errors = _run(_load(tmp_path)).errors
    assert any("ZZ-99" in e and "no spec defines" in e for e in errors)
    assert not any("ZZ-01" in e for e in errors)


def test_real_bundle_is_clean_in_ci_mode():
    """The repo's own spec bundle passes the strict CI checks."""
    mod = _load(REPO)
    rep = _run(mod, ratchet=True, baseline=mod.read_baseline(REPO / "scripts" / "acceptance-baseline.txt"))
    assert rep.errors == []
