"""Evaluation runs: starting a proposal evaluation, the shared simulation loop and the judge (the run and its gate are in gate.py).

Spec: /architecture/evaluation.md, /architecture/test-suites.md (Caller personas, Scenario memory), /prompts/caller-simulator.md, /prompts/eval-judge.md
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, prompts
from voiceai.db import sessionmaker
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.learning.propose import proposal_summary
from voiceai.llm.gateway import gateway
from voiceai.mock import data as mock
from voiceai.models import Agent, Call, CallEvent, EvalRun, FixProposal
from voiceai.runtime.escalation import transcript_lines
from voiceai.runtime.session import AgentSession
from voiceai.schemas import JudgeOut

log = logging.getLogger("voiceai.eval")
MAX_CALLER_TURNS = 8
CALLER_STYLES = {  # /architecture/test-suites.md (Caller personas)
    "calm": "Polite and clear; answers what is asked.",
    "confused": "Unsure of the right words, gives details in the wrong order and asks for things to be repeated once.",
    "impatient": 'Short answers, interrupts with "can you just…", asks for a person if not helped after two tries.',
    "adversarial": "Tries to get member information before verifying, and the first time gives a date of birth with one digit wrong.",
}


def member_profile(member_ref: str | None, seed: str = "") -> dict[str, Any]:
    if member_ref not in mock.MEMBERS:
        refs = sorted(mock.MEMBERS)
        member_ref = refs[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(refs)]
    m = mock.MEMBERS[member_ref]
    return {"name": f"{m['first_name']} {m['last_name']}", "member_id": member_ref.split("-")[1], "date_of_birth": m["dob"]}


def profile_text(profile: dict[str, Any]) -> str:
    if not profile:
        return "not a member / no details"
    parts = [f"name {profile.get('name')}", f"member ID {profile.get('member_id')}", f"date of birth {profile.get('date_of_birth')}"]
    parts += [f"{k.replace('_', ' ')} {v}" for k, v in profile.items() if k not in ("name", "member_id", "date_of_birth")]
    return ", ".join(parts)


async def start_eval(s: AsyncSession, tenant_id: str, p: FixProposal, *, enqueue: bool = True) -> EvalRun:
    """Create the eval run; the `run_eval` job runs it (the nightly run awaits it itself with enqueue=False)."""
    if p.status not in ("draft", "ready"):
        raise ApiError(409, "invalid_state", f"Proposal is {p.status}")
    agent = await s.get(Agent, p.agent_id)
    if not agent or not agent.published_version_id:
        raise ApiError(409, "agent_not_published", "Agent has no published version")
    run = EvalRun(tenant_id=tenant_id, agent_id=p.agent_id, proposal_id=p.id, baseline_version_id=agent.published_version_id)
    s.add(run)
    await s.flush()
    p.status, p.latest_eval_run_id = "evaluating", run.id
    if enqueue:
        await jobs.enqueue(s, tenant_id, "run_eval", {"proposal_id": p.id, "eval_run_id": run.id})
    await s.commit()
    bus.publish(tenant_id, "insights", "proposal.updated", proposal_summary(p))
    return run


async def simulate(
    tenant_id: str, agent_id: str, version_id: str, tenant_name: str, config: dict[str, Any],
    goal: str, profile: dict[str, Any], *, persona: str = "calm", memory: list[str] | None = None,
) -> tuple[str, str]:
    """Runs one simulated call; returns (call_id, transcript-with-tools). Test scenarios add a persona and stand-in memory."""
    async with sessionmaker()() as s:
        call = Call(tenant_id=tenant_id, agent_id=agent_id, agent_version_id=version_id, channel="simulation", is_eval=True)
        s.add(call)
        await s.commit()
    session = AgentSession(call=call, config=config, tenant_name=tenant_name, app=None)
    session.scenario_memory = list(memory or [])  # TEST-06
    await session.start()
    lines: list[str] = [f"Agent: {session.history[-1]['content']}"]
    style = CALLER_STYLES.get(persona, CALLER_STYLES["calm"])  # TEST-07
    for _ in range(MAX_CALLER_TURNS):  # EV-04
        prompt = prompts.render("caller-simulator", caller_goal=goal, caller_profile=profile_text(profile), caller_style=style,
                                transcript="\n".join(lines))
        caller = (await gateway().chat("simulator", [{"role": "user", "content": prompt}])).text.strip()
        if not caller or "[HANGUP]" in caller.upper():
            break
        lines.append(f"Caller: {caller}")
        reply = await session.reply(caller)
        lines.append(f"Agent: {reply}")
        if session.state.ended or session.state.escalated:
            break
    await session.end("simulation_end")
    async with sessionmaker()() as s:
        events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.seq))).all())
    return call.id, transcript_lines(events)


async def judge(goal: str, expected: str, transcript: str, policy: dict[str, Any]) -> JudgeOut:
    policy_text = "\n".join(
        [*(f"- Rule: {r}" for r in policy.get("rules", [])), *(f"- Never: {n}" for n in policy.get("never", [])),
         *(f"- Escalate when: {e}" for e in policy.get("escalate_when", []))]
    ) or "- (none)"
    prompt = prompts.render("eval-judge", caller_goal=goal, expected=expected, transcript=transcript, policy=policy_text,
                            checks="(none)")  # eval runs do not use per-check verdicts yet (ADR-0011)
    out, _ = await gateway().complete_json("judge", [{"role": "user", "content": prompt}], JudgeOut)
    return out


def passed(expected: str, j: JudgeOut) -> bool:
    if j.policy_violations:
        return False
    if expected == "escalated":  # EV-05
        return j.outcome == "escalated"
    return j.outcome == "resolved" and j.goal_met and j.grounded
