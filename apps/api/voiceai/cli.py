"""Command line: serve, seed, reindex, chat, eval-scenarios.

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
    from voiceai.core import db
    from voiceai.composition.seed.loader import seed

    db.configure()
    await db.init_db(drop=args.reset)
    summary = await seed(reset=False)
    print(summary)


async def _reindex(_: argparse.Namespace) -> None:
    from sqlalchemy import select

    from voiceai.core import db
    from voiceai.modules.knowledge.service import rechunk
    from voiceai.core.tables import KnowledgeDoc

    db.configure()
    async with db.sessionmaker()() as s:
        docs = (await s.scalars(select(KnowledgeDoc))).all()
        for d in docs:
            await rechunk(s, d)
        await s.commit()
    print(f"re-embedded {len(docs)} documents")


async def _chat(args: argparse.Namespace) -> None:
    from voiceai.core import db, jobs
    from voiceai.modules.conversation.session import AgentSession, create_call

    db.configure()
    jobs.install_handlers()  # the post-call analysis this drains at the end needs its handler
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


async def _eval_scenarios(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from voiceai.core import db
    from voiceai.modules.learning.evaluate import judge, passed, simulate
    from voiceai.core.tables import Agent, AgentVersion, EvalScenario, Tenant

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
    args = p.parse_args(argv)
    if args.cmd == "serve":
        _serve(args)
        return
    handler = {"seed": _seed, "reindex": _reindex, "chat": _chat, "eval-scenarios": _eval_scenarios}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main(sys.argv[1:])
