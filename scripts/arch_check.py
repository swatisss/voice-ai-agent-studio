#!/usr/bin/env python3
"""Architecture checks: the module boundaries of the backend package.

Spec: /architecture/modular-structure.md, /process/conventions.md (Code traceability)

Static rules (stdlib only, so this runs in git hooks and CI without a venv):
  * MOD-01 a module reaches another module only through its `contract` module, acyclically
  * MOD-02 modules never import adapters; only `composition/` and `core/` may
  * MOD-03 `ports/` imports nothing internal but `ports`
  * MOD-04 only the voice module imports pipecat
  * MOD-05 every module names a governing spec that exists
  * MOD-06 nothing in the product imports the simulated business system
  * MOD-07 no ORM relationship() crosses a module's tables

MOD-08 (job handlers are registered explicitly) is a property of the built app, so it is
checked by the test suite rather than here.

Rules over folders that do not exist yet pass vacuously: this file is the ratchet that keeps
them true from the moment each folder appears.

Exit code 0 = ok, 1 = errors.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "apps" / "api" / "voiceai"
SPECS = ROOT / "specs"

PACKAGE = "voiceai"
SPEC_RE = re.compile(r"Spec:\s*(.+)")
SPEC_PATH_RE = re.compile(r"/[A-Za-z0-9_./-]+\.md")

# The voice module is the only place Pipecat may be imported. Both spellings are "the voice
# module": the second is where it lives before the package is split into modules/.
VOICE_DIRS = ("modules/voice", "voice")
# Folders that already hold a target layer's code under their pre-split name. `llm/` holds the
# gateway, which is core infrastructure and moves to `core/llm/`.
PRE_SPLIT_LAYERS = {"llm": "core"}
CONFINED = ("pipecat",)
# Adapters are constructed by the composition root; core may hold a factory over a port.
ADAPTER_IMPORTERS = ("composition", "core", "adapters")
SIMULATED_SYSTEM = "businessmock"
TABLES = "tables.py"


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def sources() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if p.read_text(encoding="utf-8").strip())


def where(path: str) -> tuple[str, str | None]:
    """Classify a package-relative path as (layer, module). Layer "root" is unlayered code."""
    parts = path.split("/")
    top = parts[0]
    if top == "modules":
        return "modules", (parts[1] if len(parts) > 1 else None)
    if top in ("ports", "adapters", "core", "composition"):
        return top, None
    if top in PRE_SPLIT_LAYERS:
        return PRE_SPLIT_LAYERS[top], None
    return "root", None


def internal_imports(tree: ast.AST, pkg_path: str) -> list[tuple[str, int]]:
    """Package-relative dotted targets imported by this file, with line numbers.

    `from voiceai.core.db import x` -> "core.db"; `from . import y` is resolved against the
    importing file's own package so relative imports are classified like absolute ones.
    """
    here = pkg_path.rsplit("/", 1)[0] if "/" in pkg_path else ""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PACKAGE or alias.name.startswith(PACKAGE + "."):
                    out.append((alias.name[len(PACKAGE) + 1:], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: walk up from this file's own package
                base = here.split("/") if here else []
                up = node.level - 1
                base = base[: len(base) - up] if up <= len(base) else []
                target = ".".join([*base, *( [node.module] if node.module else [] )])
                out.append((target.replace("/", "."), node.lineno))
            elif node.module and (node.module == PACKAGE or node.module.startswith(PACKAGE + ".")):
                out.append((node.module[len(PACKAGE) + 1:], node.lineno))
    return out


def external_imports(tree: ast.AST) -> list[tuple[str, int]]:
    """Top-level distribution names imported by this file, with line numbers."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            out.append((node.module.split(".")[0], node.lineno))
    return out


def spec_targets(tree: ast.AST) -> list[str] | None:
    """Bundle-absolute spec paths from the module docstring, or None when there is no Spec: line."""
    doc = ast.get_docstring(tree) or ""
    match = SPEC_RE.search(doc)
    if not match:
        return None
    return SPEC_PATH_RE.findall(match.group(1))


def calls_relationship(tree: ast.AST) -> bool:
    """True when this module actually calls relationship(), however it was imported."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "relationship":
            return True
    return False


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """One cycle in a directed graph, as the path that closes it, or None."""
    state: dict[str, int] = {}
    stack: list[str] = []

    def walk(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt) == 1:
                return [*stack[stack.index(nxt):], nxt]
            if state.get(nxt, 0) == 0:
                found = walk(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            found = walk(node)
            if found:
                return found
    return None


def check(rep: Report) -> None:
    graph: dict[str, set[str]] = {}
    for path in sources():
        pkg_path = path.relative_to(PKG).as_posix()
        layer, module = where(pkg_path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            rep.err(f"{rel(path)}: cannot parse ({exc.msg})")
            continue

        # MOD-05: a governing spec, and one that exists.
        targets = spec_targets(tree)
        if targets is None:
            rep.err(f"MOD-05 {rel(path)}: module docstring has no `Spec: /<file>.md` line")
        elif not targets:
            rep.err(f"MOD-05 {rel(path)}: `Spec:` line names no bundle-absolute .md path")
        else:
            for target in targets:
                if not (SPECS / target.lstrip("/")).exists():
                    rep.err(f"MOD-05 {rel(path)}: Spec: {target} does not exist")

        # MOD-04: Pipecat stays in the voice module.
        if not pkg_path.startswith(VOICE_DIRS):
            for name, line in external_imports(tree):
                if name in CONFINED:
                    rep.err(f"MOD-04 {rel(path)}:{line}: imports {name}; only {VOICE_DIRS[0]}/ may")

        # MOD-07: cross-module ORM relationships. Matched on the parse tree, not the file text, so
        # that the word in a docstring explaining the rule is not itself reported as a violation.
        if path.name == TABLES and calls_relationship(tree):
            rep.err(f"MOD-07 {rel(path)}: relationship() in {TABLES}; link modules by id column instead")

        if layer == "modules" and module:
            graph.setdefault(module, set())

        for target, line in internal_imports(tree, pkg_path):
            t_layer, t_module = where(target.replace(".", "/"))

            # MOD-03: ports are a leaf.
            if layer == "ports" and t_layer != "ports":
                rep.err(f"MOD-03 {rel(path)}:{line}: ports may not import {PACKAGE}.{target}")

            # MOD-02: adapters are wired by the composition root.
            if t_layer == "adapters":
                if layer == "modules":
                    rep.err(f"MOD-02 {rel(path)}:{line}: module `{module}` imports adapter {target}; "
                            f"depend on a port and let composition/ inject the adapter")
                elif layer not in ADAPTER_IMPORTERS:
                    rep.err(f"MOD-02 {rel(path)}:{line}: only {'/, '.join(ADAPTER_IMPORTERS)}/ may import adapters")

            if layer != "modules" or not module:
                continue

            # MOD-06: the simulated business system is not a dependency of the product.
            if t_module == SIMULATED_SYSTEM and module != SIMULATED_SYSTEM:
                rep.err(f"MOD-06 {rel(path)}:{line}: module `{module}` imports the simulated "
                        f"business system ({target}); only composition/ may")
                continue

            # MOD-01: cross-module access goes through `contract`.
            if t_layer == "modules" and t_module and t_module != module:
                parts = target.split(".")
                if len(parts) < 3 or parts[2] != "contract":
                    rep.err(f"MOD-01 {rel(path)}:{line}: module `{module}` imports {target}; "
                            f"use modules.{t_module}.contract")
                graph.setdefault(module, set()).add(t_module)

    # MOD-01: the contract graph is acyclic.
    cycle = find_cycle(graph)
    if cycle:
        rep.err(f"MOD-01 module dependency cycle: {' -> '.join(cycle)}; break it with a port in "
                f"ports/ so one side stops naming the other")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rep = Report()
    check(rep)
    for w in rep.warnings:
        if not args.quiet:
            print(f"warning: {w}")
    for e in rep.errors:
        print(f"error: {e}")
    if not args.quiet:
        print(f"arch_check: {len(rep.errors)} error(s); {len(sources())} modules checked")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
