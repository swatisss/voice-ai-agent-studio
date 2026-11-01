"""A scripted stand-in for every LLM role, so the demo walkthrough runs with no API keys and no cost.

Spec: /product/demo-walkthrough.md (Automated run, fake mode)

It is not a model. The agent searches knowledge for every question and answers with the sentences of the best result
that share the most words with the question; it calls get_claim_documents once it knows the claim type, refuses to
promise payment, ends the call on a goodbye and escalates when the caller's words meet the agent's escalation rules.
The simulated caller states its goal and hangs up once answered. The judge passes every check, and analysis, packets,
memory and fix drafts are built from the transcript and evidence they are given. Good for checking plumbing and the
demo's flow; it says nothing about answer quality.
"""
from __future__ import annotations

import json
import re
from typing import Any

from voiceai.llm.gateway import FakeReply

STOP = set("a an the and or but if of to in on at for with by from is are was were be been am do does did i me my you your we our "
           "it its this that these those there what which who how much many can could would should will about any some please "
           "hi hello thanks thank yes no not get got".split())
GENERIC = {"caller", "callers", "customer", "member", "members", "someone", "person", "specialist", "request", "wants", "asks",
           "travel", "travelling", "traveling", "trip", "abroad", "policy", "plan", "health", "cover", "covered", "coverage",
           "claim", "claims", "insurance", "know", "want", "need", "help", "tell", "much", "safetrip", "standard"}
GOODBYE = re.compile(r"\b(bye|goodbye|that's (all|everything)|that is all|nothing else)\b", re.I)
HANDOFF_ASK = re.compile(r"\b(speak|talk) to (a|an|someone|a real) (person|human|agent)|\breal person\b|\bconnect me\b", re.I)
CLAIM_TYPES = {"outpatient": ("outpatient", "doctor", "gp", "clinic"), "urgent_care": ("urgent",),
               "inpatient": ("inpatient", "hospital stay", "admitted"), "dental": ("dental", "dentist", "tooth")}


SYNONYMS = {"newborn": "baby", "newborns": "baby", "babies": "baby", "infant": "baby", "suitcase": "baggage", "luggage": "baggage",
            "bag": "baggage", "phone": "phones", "mobile": "phones"}


def words(text: str) -> set[str]:
    found = (w for w in re.findall(r"[a-z0-9$,'-]+", text.lower()) if len(w) > 2 and w not in STOP)
    return {SYNONYMS.get(w, w) for w in found}


def sentences(text: str) -> list[str]:
    plain = re.sub(r"^#+ .*$", "", text, flags=re.M)
    return [s.strip().lstrip("-* ") for s in re.split(r"(?<=[.!?])\s+|\n+", plain) if len(s.strip()) > 15]  # list items read as sentences


def best_sentences(question: str, content: str, n: int = 2) -> str:
    """The sentences sharing the most question words, rare words counting more (1 / sentences containing the word)."""
    q, pool = {w for w in words(question) if w not in GENERIC and len(w) > 3}, sentences(content)
    df = {w: sum(1 for s in pool if w in words(s)) for w in q}
    score = lambda s: sum(1 / df[w] for w in q & words(s) if df[w])  # noqa: E731
    ranked = sorted(pool, key=lambda s: -score(s))
    picked = [s for s in ranked[:n] if score(s) > 0] or ranked[:1]
    return " ".join(picked)


# ------------------------------------------------------------------ the agent (role realtime)
def _last_user(messages: list[dict[str, Any]]) -> str:
    return next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")


def _escalation_rules(system: str) -> list[str]:
    block = system.split("# Escalate by calling escalate_to_human when", 1)[-1].split("After calling", 1)[0]
    return [line[2:].strip() for line in block.splitlines() if line.startswith("- ")]


def _answer_from_tool(name: str, result: dict[str, Any], question: str) -> FakeReply:
    if name == "search_knowledge":
        if result.get("no_answer") or not result.get("results"):
            return FakeReply(text="I don't have approved information on that. Would you like me to connect you with a specialist?")
        content = "\n".join(r.get("content", "") for r in result["results"])  # the best sentences across every result
        return FakeReply(text=best_sentences(question, content) + " Is there anything else I can help with?")
    if name == "get_claim_documents" and isinstance(result.get("documents"), list):
        docs = [d.get("document") or d.get("name") for d in result["documents"] if isinstance(d, dict)]
        return FakeReply(text="Please send: " + "; ".join(d for d in docs if d) + ". Send everything within 30 days of returning home.")
    if result.get("say"):
        return FakeReply(text=str(result["say"]))
    return FakeReply(text="Thanks, that's done. Is there anything else I can help with?")


def agent(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> FakeReply:
    system = str(messages[0].get("content") or "") if messages else ""
    names = {t.get("function", {}).get("name") or t.get("name") for t in tools or []}
    question = _last_user(messages)
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":  # answer from the tool that just returned
        call = next((m for m in reversed(messages) if m.get("role") == "assistant" and m.get("tool_calls")), {})
        name = (call.get("tool_calls") or [{}])[-1].get("function", {}).get("name", "")
        try:
            result = json.loads(last.get("content") or "{}")
        except ValueError:
            result = {}
        return _answer_from_tool(name, result if isinstance(result, dict) else {}, question)
    if GOODBYE.search(question):
        return FakeReply(text="Thank you for calling. Goodbye!", tool_calls=[("end_call", {"summary": "Answered the caller's questions."})])
    asked = words(question)
    if HANDOFF_ASK.search(question) or any(asked & {w for w in words(rule) if len(w) > 5 and w not in GENERIC} for rule in _escalation_rules(system)[1:-1]):
        return FakeReply(tool_calls=[("escalate_to_human", {"reason_category": "policy_required", "reason_detail": question[:200]})])
    if "promise" in question.lower():
        return FakeReply(text="I can't promise that a claim will be paid; claims are assessed against the policy and the documents you send.")
    if "get_claim_documents" in names and re.search(r"\b(document|paperwork|send)\b", question, re.I):
        return FakeReply(text="Was this a doctor visit, urgent care, a hospital stay or dental treatment?")
    claim_type = next((t for t, keys in CLAIM_TYPES.items() if any(k in question.lower() for k in keys)), None)
    previous = next((str(m.get("content") or "") for m in reversed(messages[:-1]) if m.get("role") == "assistant" and m.get("content")), "")
    if "get_claim_documents" in names and claim_type and "hospital stay" in previous:
        return FakeReply(tool_calls=[("get_claim_documents", {"claim_type": claim_type})])
    return FakeReply(tool_calls=[("search_knowledge", {"query": question[:200]})])


# ------------------------------------------------------------------ the simulated caller (role simulator)
def caller(prompt: str) -> str:
    goal = re.search(r"Your goal: (.+)", prompt)
    transcript = prompt.split("Conversation so far:", 1)[-1]
    turns = transcript.count("\nCaller:")
    agent_lines = re.findall(r"^Agent: (.*)$", transcript, flags=re.M)
    if turns == 0 and goal:
        text = goal.group(1).strip()
        for a, b in ((r"\bYou are\b", "I am"), (r"\bYou have\b", "I have"), (r"\bYou want\b", "I want"), (r"\bYou\b", "I"),
                     (r"\byou\b", "I"), (r"\bYour\b", "My"), (r"\byour\b", "my")):
            text = re.sub(a, b, text)
        return "Hi. " + text
    last = agent_lines[-1] if agent_lines else ""
    if re.search(r"don't have approved information|can't help|cannot help", last, re.I):
        return "Yes, please connect me with a specialist."  # not answered: a real caller takes the offer
    if turns >= 3 or "?" not in last or re.search(r"anything else|connect you|specialist", last, re.I):
        return "[HANGUP]"  # answered: a real caller says goodbye instead of inventing new questions
    if re.search(r"doctor visit|urgent care|hospital stay|dental", last, re.I):
        return "It was a regular doctor visit."
    return "I'd rather not say. Thanks anyway. [HANGUP]"


# ------------------------------------------------------------------ JSON roles, by output schema
def _first_caller_line(prompt: str) -> str:
    m = re.search(r"(?:Caller|User|caller): (.+)", prompt)
    return m.group(1).strip()[:200] if m else "The caller had a question."


def goal_answered(prompt: str) -> bool:
    """The agent's lines share a distinctive word with the caller's goal and never say the answer is missing."""
    goal = re.search(r"Caller goal: (.+)", prompt)
    said = " ".join(re.findall(r"Agent: (.+)", prompt))
    if not goal or re.search(r"don't have approved information", said, re.I):
        return False
    distinctive = {w for w in words(goal.group(1)) if w not in GENERIC and len(w) > 3}
    return bool(distinctive & words(said))


def json_reply(role: str, prompt: str, schema: str) -> dict[str, Any]:
    escalated = "escalate_to_human" in prompt or "Escalated" in prompt
    goal = _first_caller_line(prompt)
    if schema == "JudgeOut":
        block = prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0] if "Checks:\n" in prompt else ""
        keys = [line.split(":", 1)[0] for line in block.splitlines() if line and line != "(none)"]
        checks = {k: {"verdict": "pass", "reason": "Scripted judge: passes every check.", "seqs": []} for k in keys}
        met = escalated or goal_answered(prompt)
        if "outcome.goal_met" in checks and not met:  # test runs and fix evaluations decide on this check
            checks["outcome.goal_met"] = {"verdict": "fail", "reason": "Scripted judge: the answer does not cover the goal.", "seqs": []}
        return {"outcome": "escalated" if escalated else "resolved", "goal_met": met, "grounded": True,
                "policy_violations": [], "notes": "Scripted judge (demo fake mode).", "checks": checks}
    if schema == "AnalysisOut":
        # a specialist answered what the agent could not: the answer was missing from the knowledge, and the gap is
        # described by that answer, as a real analyst would summarise it (so paraphrased questions cluster together)
        note = re.search(r"human resolution note: ([^.\n]+)", prompt)
        gap = "no approved information" in prompt.lower() or bool(escalated and note)
        safety = bool(re.search(r"hospital|emergency|safety", prompt, re.I))
        root = ("missing_knowledge" if gap else "safety" if safety else "caller_requested") if escalated else "none"
        summary = f"No approved answer; a specialist explained: {note.group(1).strip()}" if note else goal
        return {"outcome": "escalated" if escalated else "resolved", "intent": "coverage_question", "root_cause": root,
                "gap_summary": summary if gap else "", "caller_goal": goal, "resolution_summary": "Scripted analysis (demo fake mode).",
                "sentiment_start": "neutral", "sentiment_end": "neutral"}
    if schema == "Packet":
        return {"summary": f"The caller said: {goal}", "intent": "coverage_question", "entities": {}, "already_tried": [],
                "escalation_reason": {"category": "safety" if re.search(r"hospital|emergency", prompt, re.I) else "policy_required",
                                      "detail": goal}, "suggested_next_action": "Call the caller back and help with their request.",
                "caller_verified": False}
    if schema == "MemoryExtractOut":
        return {"episode": f"Called about: {goal}", "facts": []}
    if schema == "MemoryDecisionOut":
        return {"action": "NOOP", "reason": "Scripted (demo fake mode)."}
    if schema == "ClusterName":
        return {"name": "Recurring question", "description": "Callers ask about the same topic."}
    if schema == "FixDraft":
        notes = list(dict.fromkeys(m.strip() for m in re.findall(r"Specialist: ([^|\n]+)", prompt) if "(no note)" not in m))
        title = re.search(r"Cluster: (.+)", prompt)
        name = re.split(r" [—-] ", title.group(1).strip())[0] if title else "Answer to a recurring question"
        body = "\n".join(f"- {n}" for n in notes[:8]) or "- Specialists answered this question; see the evidence."
        return {"kind": "knowledge_article", "title": name, "rationale": "Built from the specialists' resolution notes (demo fake mode).",
                "article": {"title": name, "content_markdown": f"# {name}\n\n{body}\n"}}
    if schema == "Utterances":
        return {"utterances": ["I have a question about my policy.", "Can you help me with a claim?", "What does my plan cover?"]}
    if schema == "Question":
        return {"question": "Could you tell me a little more about what you need?"}
    if schema == "TurnVerdictOut":
        return {"complete": True}
    return {}


def responder(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
    """The gateway's fake responder for streamed roles (the agent and the simulated caller)."""
    if role == "simulator":
        return caller(str(messages[-1].get("content") or ""))
    return agent(messages, tools)
