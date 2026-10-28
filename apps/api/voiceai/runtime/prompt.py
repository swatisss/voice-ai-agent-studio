"""System prompt assembly for the realtime role.

Spec: /prompts/agent-system-prompt.md, /architecture/tools-and-skills.md (Skill format), /architecture/call-modes.md,
/architecture/caller-verification.md, /architecture/agent-memory.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from voiceai import prompts
from voiceai.runtime.outbound import context_lines


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


def mode_instructions(mode: str, context: dict[str, Any] | None) -> str:
    name = mode if mode in ("inbound", "outbound", "internal") else "inbound"
    return prompts.render(f"mode-{name}", call_context=context_lines(context or {})).strip()


NOT_VERIFIED = "- (not verified yet)"
NOTHING = "- (none)"


def verification_instruction(identified_first_name: str | None) -> str:
    """Flow A for a caller identified by a registered number, flow B otherwise (/architecture/caller-verification.md)."""
    if identified_first_name:
        return (f"The calling number is on {identified_first_name}'s record: greet them by first name, ask only for their date of "
                "birth and call the verification tool with it. If they say they are someone else, ask for member ID and date of "
                "birth instead.")
    return "Ask for member ID and date of birth, then call the verification tool."


def system_prompt(
    config: dict[str, Any], tenant_name: str, verified_ref: str | None, now: datetime, context: dict[str, Any] | None = None,
    identified_first_name: str | None = None, member_profile: str = NOT_VERIFIED, member_memory: str = NOTHING,
) -> str:
    persona = config.get("persona", {})
    policy = config.get("policy", {})
    skills = config.get("skills", [])
    return prompts.render(
        "agent-system-prompt",
        persona_name=persona.get("name", "Ava"),
        persona_style=persona.get("style", ""),
        tenant_name=tenant_name,
        mode_instructions=mode_instructions(config.get("mode", "inbound"), context),
        policy_rules=_lines(policy.get("rules", [])),
        escalate_when_list=_lines(policy.get("escalate_when", [])),
        never_list=_lines(policy.get("never", [])),
        skills="\n\n".join(render_skill(s) for s in skills) or "(no skills configured)",
        today=f"{now:%A}, {now:%B} {now.day}, {now.year}",
        verified=f"yes (member {verified_ref})" if verified_ref else "no",
        verification_instruction=verification_instruction(None if verified_ref else identified_first_name),
        member_profile=member_profile,
        member_memory=member_memory,
    )
