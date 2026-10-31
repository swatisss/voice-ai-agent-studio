"""Scorecard rollups per agent version, drift, reviews and judge calibration - computed on read.

Spec: /architecture/call-scoring.md (Reviews and calibration, Rollups), /api/rest-api.md (Evaluation)
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import utcnow
from voiceai.learning.scoring import nearest_rank
from voiceai.models import AgentVersion, Call, CallFeedback, CallScorecard, CheckReview

CALIBRATION_MIN_REVIEWS = 20
CALIBRATION_MIN_AGREEMENT = 0.85
DRIFT_MIN_CALLS = 20
DRIFT_POINTS = 0.10
DRIFT_METRICS = {"goal_met": "outcome.goal_met", "grounded": "knowledge.grounded"}


def review_out(r: CheckReview) -> dict[str, Any]:
    return {"check_key": r.check_key, "verdict": r.verdict, "judge_verdict": r.judge_verdict, "note": r.note or "",
            "reviewer": r.reviewer, "at": (r.updated_at or r.created_at).isoformat()}


def scorecard_out(card: CallScorecard, reviews: list[CheckReview]) -> dict[str, Any]:
    keys = {c["key"] for c in card.checks}
    return {
        "id": card.id, "call_id": card.call_id, "agent_version_id": card.agent_version_id, "measures": card.measures,
        "checks": card.checks, "hard_fail": card.hard_fail, "score": card.score, "judged": card.judged,
        "judge_model": card.judge_model, "source": card.source, "updated_at": card.updated_at.isoformat(),
        "reviews": {r.check_key: review_out(r) for r in reviews if r.check_key in keys},
    }


def _verdict(card: CallScorecard, key: str) -> str | None:
    return next((c["verdict"] for c in card.checks if c["key"] == key), None)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def pass_rate(cards: list[CallScorecard], key: str) -> tuple[float | None, int]:
    verdicts = [_verdict(c, key) for c in cards]
    passes, fails = verdicts.count("pass"), verdicts.count("fail")
    return _rate(passes, passes + fails), passes + fails


def calibration(reviews: list[CheckReview]) -> dict[str, Any]:
    """Agreement, catch rate and the constant-answer baseline of one check's reviews (SC-09)."""
    judged = [r for r in reviews if r.judge_verdict != "not_judged"]
    agree = sum(1 for r in judged if r.verdict == r.judge_verdict)
    human_fails = [r for r in judged if r.verdict == "fail"]
    common = Counter(r.verdict for r in judged).most_common(1)
    agreement = _rate(agree, len(judged))
    return {
        "reviews": len(judged),
        "agreement": agreement,
        "catch_rate": _rate(sum(1 for r in human_fails if r.judge_verdict == "fail"), len(human_fails)),
        "baseline": _rate(common[0][1], len(judged)) if common else None,
        "calibrated": len(judged) >= CALIBRATION_MIN_REVIEWS and agreement is not None and agreement >= CALIBRATION_MIN_AGREEMENT,
    }


def _metrics(calls: list[Call], cards: dict[str, CallScorecard]) -> dict[str, float | None]:
    scored = [cards[c.id] for c in calls if c.id in cards]
    out = {"containment": _rate(sum(1 for c in calls if c.outcome == "resolved"), len(calls))}
    for name, key in DRIFT_METRICS.items():
        out[name] = pass_rate(scored, key)[0]
    return out


def drift(calls: list[Call], cards: dict[str, CallScorecard], now: datetime) -> list[str]:
    """SC-10: metrics whose last-7-day value is ≥ 10 points below the version's first 7 days (≥ 20 scored calls in each)."""
    scored = sorted((c for c in calls if c.id in cards), key=lambda c: c.started_at)
    if not scored:
        return []
    first_end = _aware(scored[0].started_at) + timedelta(days=7)
    first = [c for c in scored if _aware(c.started_at) < first_end]
    last = [c for c in scored if _aware(c.started_at) >= now - timedelta(days=7)]
    if len(first) < DRIFT_MIN_CALLS or len(last) < DRIFT_MIN_CALLS or set(c.id for c in first) & set(c.id for c in last):
        return []
    before, after = _metrics(first, cards), _metrics(last, cards)
    return [k for k in ("goal_met", "grounded", "containment")
            if before[k] is not None and after[k] is not None and before[k] - after[k] >= DRIFT_POINTS - 1e-9]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _calls(s: AsyncSession, tenant_id: str, agent_id: str, since: datetime | None, include_seed: bool) -> list[Call]:
    q = select(Call).where(Call.tenant_id == tenant_id, Call.agent_id == agent_id, Call.is_eval.is_(False),
                           Call.channel != "simulation", Call.ended_at.is_not(None))
    if since is not None:
        q = q.where(Call.started_at >= since)
    if not include_seed:
        q = q.where(Call.is_seed.is_(False))
    return list((await s.scalars(q.order_by(Call.started_at))).all())


async def _cards(s: AsyncSession, call_ids: list[str]) -> dict[str, CallScorecard]:
    if not call_ids:
        return {}
    rows = (await s.scalars(select(CallScorecard).where(CallScorecard.call_id.in_(call_ids)))).all()
    return {r.call_id: r for r in rows}


async def summary(s: AsyncSession, tenant_id: str, agent_id: str, days: int, include_seed: bool) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=days)
    all_calls = await _calls(s, tenant_id, agent_id, None, include_seed)
    all_cards = await _cards(s, [c.id for c in all_calls])
    calls = [c for c in all_calls if _aware(c.started_at) >= since]
    cards = {k: v for k, v in all_cards.items() if k in {c.id for c in calls}}
    feedback = dict((await s.execute(select(CallFeedback.call_id, CallFeedback.rating)
                                     .where(CallFeedback.call_id.in_([c.id for c in calls] or [""])))).all())
    versions = {v.id: v for v in (await s.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id))).all()}

    by_version: dict[str, list[Call]] = defaultdict(list)
    for c in calls:
        by_version[c.agent_version_id].append(c)
    version_rows = []
    for vid, vcalls in by_version.items():
        v = versions.get(vid)
        vcards = [cards[c.id] for c in vcalls if c.id in cards]
        escalated = [cards[c.id] for c in vcalls if c.outcome == "escalated" and c.id in cards]
        rated = [feedback[c.id] for c in vcalls if c.id in feedback]
        latencies = [x for card in vcards for x in card.measures.get("latencies_ms") or []]
        firsts = [card.measures["first_response_ms"] for card in vcards if card.measures.get("first_response_ms") is not None]
        p50s = [card.measures["latency_p50_ms"] for card in vcards if card.measures.get("latency_p50_ms") is not None]
        keys = {ch["key"] for card in vcards for ch in card.checks}
        version_rows.append({
            "version_id": vid, "version": v.version if v else None, "published_at": v.created_at.isoformat() if v else None,
            "calls": len(vcalls), "scored": len(vcards),
            "containment_rate": _rate(sum(1 for c in vcalls if c.outcome == "resolved"), len(vcalls)),
            "correct_escalation_rate": _rate(sum(1 for card in escalated if _verdict(card, "outcome.escalation_appropriate") == "pass"), len(vcalls)),
            "unnecessary_escalation_rate": _rate(sum(1 for card in escalated if _verdict(card, "outcome.escalation_appropriate") == "fail"), len(vcalls)),
            "abandonment_rate": _rate(sum(1 for c in vcalls if c.outcome == "abandoned"), len(vcalls)),
            "hard_fail_calls": sum(1 for card in vcards if card.hard_fail),
            "thumbs_up_rate": _rate(rated.count("up"), len(rated)),
            "first_response_ms": int(statistics.median(firsts)) if firsts else None,
            "latency_p50_ms": int(statistics.median(p50s)) if p50s else None,
            "latency_p95_ms": nearest_rank(latencies, 0.95),
            "drift": drift([c for c in all_calls if c.agent_version_id == vid], all_cards, now),
            "check_pass_rates": {k: pass_rate(vcards, k)[0] for k in sorted(keys)},
        })
    version_rows.sort(key=lambda r: r["version"] or 0, reverse=True)

    period_cards = list(cards.values())
    reviews = list((await s.scalars(select(CheckReview).where(CheckReview.scorecard_id.in_([c.id for c in period_cards] or [""])))).all())
    reviews_by_key: dict[str, list[CheckReview]] = defaultdict(list)
    for r in reviews:
        reviews_by_key[r.check_key].append(r)
    heads: dict[str, dict[str, Any]] = {}
    for card in sorted(period_cards, key=lambda c: c.updated_at):  # the newest text of each key wins
        for ch in card.checks:
            heads[ch["key"]] = {k: ch.get(k) for k in ("key", "group", "method", "hard_gate", "text", "source")}
    checks = []
    for key, head in heads.items():
        rate, decided = pass_rate(period_cards, key)
        cal = calibration(reviews_by_key.get(key, [])) if head["method"] == "judge" else {
            "reviews": 0, "agreement": None, "catch_rate": None, "baseline": None, "calibrated": None}
        checks.append({**head, "pass_rate": rate, "decided": decided, **cal})

    daily: dict[str, list[Call]] = defaultdict(list)
    for c in calls:
        daily[_aware(c.started_at).date().isoformat()].append(c)
    daily_rows = []
    for day in sorted(daily):
        dcalls = daily[day]
        dcards = [cards[c.id] for c in dcalls if c.id in cards]
        daily_rows.append({
            "date": day, "calls": len(dcalls),
            "containment_rate": _rate(sum(1 for c in dcalls if c.outcome == "resolved"), len(dcalls)),
            "goal_met_rate": pass_rate(dcards, "outcome.goal_met")[0],
            "grounded_rate": pass_rate(dcards, "knowledge.grounded")[0],
            "hard_fails": sum(1 for card in dcards if card.hard_fail),
        })
    return {"versions": version_rows, "checks": checks, "daily": daily_rows}


async def list_scorecards(
    s: AsyncSession, tenant_id: str, agent_id: str, *, days: int, include_seed: bool, version_id: str | None = None,
    check: str | None = None, verdict: str | None = None, hard_fail: bool | None = None, reviewed: bool | None = None,
) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    calls = {c.id: c for c in await _calls(s, tenant_id, agent_id, since, include_seed)}
    cards = await _cards(s, list(calls))
    feedback = dict((await s.execute(select(CallFeedback.call_id, CallFeedback.rating)
                                     .where(CallFeedback.call_id.in_(list(calls) or [""])))).all())
    review_counts = Counter((await s.scalars(select(CheckReview.scorecard_id)
                                             .where(CheckReview.scorecard_id.in_([c.id for c in cards.values()] or [""])))).all())
    versions = dict((await s.execute(select(AgentVersion.id, AgentVersion.version).where(AgentVersion.agent_id == agent_id))).all())
    items = []
    for call_id, card in cards.items():
        call = calls[call_id]
        if version_id and card.agent_version_id != version_id:
            continue
        if check and verdict and _verdict(card, check) != verdict:
            continue
        if check and not verdict and _verdict(card, check) is None:
            continue
        if hard_fail is not None and card.hard_fail != hard_fail:
            continue
        n = review_counts.get(card.id, 0)
        if reviewed is not None and (n > 0) != reviewed:
            continue
        items.append({
            "call_id": call_id, "started_at": call.started_at.isoformat(), "version": versions.get(card.agent_version_id),
            "outcome": call.outcome, "feedback": feedback.get(call_id), "score": card.score, "hard_fail": card.hard_fail,
            "judged": card.judged, "failed_checks": [c["key"] for c in card.checks if c["verdict"] == "fail"], "review_count": n,
        })
    items.sort(key=lambda i: i["started_at"], reverse=True)
    return items[:200]
