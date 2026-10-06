"""SDD tooling: spec_check.py on synthetic bundles. Covers: SDD-01, SDD-02, SDD-03, SDD-04"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load(tmp: Path):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("spec_check", REPO / "scripts" / "spec_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.ROOT, mod.SPECS = tmp, tmp / "specs"
    return mod


def _concept(type_: str = "Component Spec", body: str = "") -> str:
    return f"---\ntype: {type_}\ntitle: X\ndescription: Y\nstatus: stable\n---\n# Body\n{body}\n"


def _bundle(tmp: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = tmp / "specs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _run(mod):  # noqa: ANN001, ANN202
    rep = mod.Report()
    files = mod.lint_files(rep)
    mod.check_indexes(rep)
    mod.check_links(rep, files)
    mod.collect_acceptance(rep, files)
    return rep


def test_missing_type_fails(tmp_path):
    """Covers: SDD-02"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": "# no frontmatter\n"})
    rep = _run(_load(tmp_path))
    assert any("missing YAML frontmatter" in e for e in rep.errors)


def test_duplicate_acceptance_ids_fail(tmp_path):
    """Covers: SDD-03"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n* [b](b.md) - b\n",
                       "a.md": _concept(body="- **ES-01** — Given x, then y."), "b.md": _concept(body="- **ES-01** — Given z, then w.")})
    rep = _run(_load(tmp_path))
    assert any("duplicate acceptance ID ES-01" in e for e in rep.errors)


def test_index_must_list_concepts(tmp_path):
    """Covers: SDD-04"""
    _bundle(tmp_path, {"index.md": "* [a](a.md) - a\n", "a.md": _concept(), "b.md": _concept()})
    rep = _run(_load(tmp_path))
    assert any("does not list b.md" in e for e in rep.errors)


def test_spec_first_rule(tmp_path):
    """Covers: SDD-01"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "x.py").write_text("print(1)\n")
    subprocess.run(["git", "add", "apps/x.py"], cwd=tmp_path, check=True)
    mod = _load(tmp_path)
    msg = tmp_path / "MSG"
    msg.write_text("Change behavior")
    rep = mod.Report()
    mod.check_spec_first(rep, str(msg))
    assert rep.errors and "spec-first rule" in rep.errors[0]
    msg.write_text("Refactor only [no-spec]")
    rep = mod.Report()
    mod.check_spec_first(rep, str(msg))
    assert not rep.errors


def test_real_bundle_is_clean():
    """The repo's own spec bundle passes."""
    rep = _run(_load(REPO))
    assert rep.errors == []
