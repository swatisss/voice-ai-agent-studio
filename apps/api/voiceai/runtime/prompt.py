"""System prompt assembly for the realtime role.

Spec: /prompts/agent-system-prompt.md, /architecture/tools-and-skills.md (Skill format)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from voiceai import prompts


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def render_skill(skill: dict[str, Any]) -> str:
    tools = ", ".join(skill.get("required_tools") or []) or "(none)"
    return (
        f"## Skill: {skill['name']}\n"
        f"Use when: {skill.get('description', '')}\n"
        f"Tools: {tools}\n"
        f"Steps:\n{skill.get('instructions', '').strip()}\n"
        f"Escalate when: {skill.get('escalate_when') or '(not specified)'}"
    )


def system_prompt(config: dict[str, Any], tenant_name: str, verified_ref: str | None, now: datetime) -> str:
    persona = config.get("persona", {})
    policy = config.get("policy", {})
    skills = config.get("skills", [])
    return prompts.render(
        "agent-system-prompt",
        persona_name=persona.get("name", "Ava"),
        persona_style=persona.get("style", ""),
        tenant_name=tenant_name,
        policy_rules=_lines(policy.get("rules", [])),
        escalate_when_list=_lines(policy.get("escalate_when", [])),
        never_list=_lines(policy.get("never", [])),
        skills="\n\n".join(render_skill(s) for s in skills) or "(no skills configured)",
        today=f"{now:%A}, {now:%B} {now.day}, {now.year}",
        verified=f"yes (member {verified_ref})" if verified_ref else "no",
    )
