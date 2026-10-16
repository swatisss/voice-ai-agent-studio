"""Command line: serve, seed, reindex, chat, eval-scenarios, phone.

Spec: /build/runbook-local.md (Useful commands)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("voiceai.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


async def _seed(args: argparse.Namespace) -> None:
    from voiceai import db
    from voiceai.seed.loader import seed

    db.configure()
    await db.init_db(drop=args.reset)
    summary = await seed(reset=False)
    print(summary)


async def _reindex(_: argparse.Namespace) -> None:
    from sqlalchemy import select

    from voiceai import db
    from voiceai.knowledge.ingest import rechunk
    from voiceai.models import KnowledgeDoc

    db.configure()
    async with db.sessionmaker()() as s:
        docs = (await s.scalars(select(KnowledgeDoc))).all()
        for d in docs:
            await rechunk(s, d)
        await s.commit()
    print(f"re-embedded {len(docs)} documents")


async def _chat(args: argparse.Namespace) -> None:
    from voiceai import db, jobs
    from voiceai.runtime.session import AgentSession, create_call

    db.configure()
    async with db.sessionmaker()() as s:
        call = await create_call(s, args.tenant, args.agent, "text")
        await s.commit()
    session = await AgentSession.open(call.id, args.tenant)
    print(f"Agent: {await session.start()}")
    while not session.state.ended:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("/quit", "/exit"):
            break
        print(f"Agent: {await session.reply(line)}")
    await session.end("hangup")
    await jobs.drain()


async def _phone(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from voiceai import db
    from voiceai.models import Agent, PhoneNumber
    from voiceai.schemas import E164_RE

    db.configure()
    await db.init_db()
    async with db.sessionmaker()() as s:
        if args.phone_cmd == "list":
            rows = (await s.execute(select(PhoneNumber, Agent.name).outerjoin(Agent, Agent.id == PhoneNumber.agent_id).order_by(PhoneNumber.e164))).all()
            for n, name in rows:
                print(f"{n.e164}  {n.tenant_id}  {name or n.agent_id}  {n.label or ''}".rstrip())
            if not rows:
                print("no phone numbers")
            return
        e164 = args.e164.strip()
        if not E164_RE.fullmatch(e164):
            sys.exit(f"{e164!r} is not an E.164 number such as +15551234567")
        if args.phone_cmd == "remove":
            row = await s.scalar(select(PhoneNumber).where(PhoneNumber.e164 == e164))
            if row is None:
                sys.exit(f"{e164} is not mapped")
            await s.delete(row)
            await s.commit()
            print(f"removed {e164}")
            return
        agent = await s.scalar(select(Agent).where(Agent.tenant_id == args.tenant, (Agent.id == args.agent) | (Agent.name == args.agent)))
        if agent is None:
            sys.exit(f"no agent {args.agent!r} in {args.tenant}")
        if await s.scalar(select(PhoneNumber.id).where(PhoneNumber.e164 == e164)):
            sys.exit(f"{e164} is already routed to an agent")
        s.add(PhoneNumber(tenant_id=args.tenant, e164=e164, agent_id=agent.id, label=args.label))
        await s.commit()
        print(f"{e164} -> {agent.name} ({args.tenant})")


async def _eval_scenarios(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from voiceai import db
    from voiceai.learning.evaluate import judge, passed, simulate
    from voiceai.models import Agent, AgentVersion, EvalScenario, Tenant

    db.configure()
    async with db.sessionmaker()() as s:
        agent = await s.get(Agent, args.agent)
        version = await s.get(AgentVersion, agent.published_version_id)
        tenant = await s.get(Tenant, agent.tenant_id)
        scenarios = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == agent.id))).all()
    total = ok = 0
    for _ in range(args.repeat):
        for sc in scenarios:
            _, transcript = await simulate(agent.tenant_id, agent.id, version.id, tenant.name, version.config, sc.caller_goal, sc.caller_profile)
            verdict = await judge(sc.caller_goal, sc.expected, transcript, version.config.get("policy", {}))
            good = passed(sc.expected, verdict)
            total += 1
            ok += good
            print(f"{'PASS' if good else 'FAIL'}  {sc.name}: {verdict.notes}")
    print(f"{ok}/{total} passed")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="voiceai")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="run the API (and web app if built)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    sd = sub.add_parser("seed", help="load demo data")
    sd.add_argument("--reset", action="store_true", help="drop all tables first")
    sub.add_parser("reindex", help="re-embed all knowledge chunks")
    ch = sub.add_parser("chat", help="text chat with an agent in the terminal")
    ch.add_argument("--agent", required=True)
    ch.add_argument("--tenant", default="evergreen-care")
    ev = sub.add_parser("eval-scenarios", help="run regression scenarios against the published version")
    ev.add_argument("--agent", required=True)
    ev.add_argument("--repeat", type=int, default=1)
    ph = sub.add_parser("phone", help="route phone numbers to agents (/architecture/telephony.md)")
    ph_sub = ph.add_subparsers(dest="phone_cmd", required=True)
    pa = ph_sub.add_parser("add", help="route a number to an agent")
    pa.add_argument("e164", help="number in international format, e.g. +15551234567")
    pa.add_argument("--agent", required=True, help="agent name or id")
    pa.add_argument("--tenant", default="evergreen-care")
    pa.add_argument("--label", default=None)
    ph_sub.add_parser("list", help="list routed numbers")
    pr = ph_sub.add_parser("remove", help="stop routing a number")
    pr.add_argument("e164")
    args = p.parse_args(argv)
    if args.cmd == "serve":
        _serve(args)
        return
    handler = {"seed": _seed, "reindex": _reindex, "chat": _chat, "eval-scenarios": _eval_scenarios, "phone": _phone}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main(sys.argv[1:])
