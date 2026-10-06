"""Loads LLM prompts verbatim from the spec bundle (specs/prompts/*.md).

Spec: /prompts/index.md, /process/sdd-workflow.md (principle 6)
"""
from __future__ import annotations

import re
from functools import lru_cache

from voiceai.config import get_settings

_BLOCK = re.compile(r"^# Prompt\s*$.*?^```text\s*$\n(.*?)^```\s*$", re.S | re.M)
_VAR = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PromptError(Exception):
    pass


@lru_cache(maxsize=32)
def load(name: str) -> str:
    path = get_settings().specs_dir / "prompts" / f"{name}.md"
    if not path.exists():
        raise PromptError(f"prompt spec not found: {path}")
    match = _BLOCK.search(path.read_text(encoding="utf-8"))
    if not match:
        raise PromptError(f"{path.name}: no ```text block under '# Prompt'")
    return match.group(1).rstrip() + "\n"


def variables(name: str) -> set[str]:
    return set(_VAR.findall(load(name)))


def render(name: str, **values: object) -> str:
    template = load(name)
    missing = variables(name) - set(values)
    if missing:
        raise PromptError(f"{name}: missing variables {sorted(missing)}")
    return _VAR.sub(lambda m: str(values[m.group(1)]), template)
