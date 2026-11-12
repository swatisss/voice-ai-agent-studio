"""Run the API with the scripted fake LLM: no provider keys, no network calls to any model, a fresh seeded database.

Spec: /product/demo-walkthrough.md (Automated run, fake mode)

    cd apps/api && uv run python ../../scripts/demo/fake_server.py --port 8010 --db <path>

scripts/demo_walkthrough.py --fake starts and stops this for you.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--db", required=True, help="SQLite file for this run (created and seeded when empty)")
    args = ap.parse_args()
    os.environ.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{Path(args.db).resolve().as_posix()}",
        "LLM_FAKE": "1", "AUTO_SEED": "1", "JOBS_ENABLED": "1",
        "EMBEDDINGS_PROVIDER": "fastembed",  # the local embedding model (CPU, no API): retrieval as in a real run
        "KNOWLEDGE_ALLOW_PRIVATE_URLS": "1",  # the demo website runs on 127.0.0.1
        # no keys at all: even a code path that skipped the fake could not reach a paid model
        "GROQ_API_KEY": "", "OPENROUTER_API_KEY": "", "OPENAI_API_KEY": "", "DEEPGRAM_API_KEY": "",
        "DECISION_MODEL_URL": "", "DECISION_MODEL_API_KEY": "", "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": "",
        "SIMLI_API_KEY": "", "LIVEKIT_API_KEY": "", "LIVEKIT_API_SECRET": "",
        # Studio sign-in on, with throwaway passwords the runner knows (scripts/demo_walkthrough.py)
        "STUDIO_ADMIN_PASSWORD": "fake-admin-pass", "STUDIO_REVIEWER_PASSWORD": "fake-reviewer-pass", "STUDIO_SESSION_SECRET": "",
    })
    sys.path.insert(0, str(HERE))
    import uvicorn

    import fake_llm
    from voiceai.llm import gateway as gw

    gw.set_fake(fake_llm.responder)
    real_complete_json = gw.Gateway.complete_json

    async def complete_json(self, role, messages, schema):  # noqa: ANN001, ANN202 - JSON roles answer by output schema
        if gw.fake_active():
            reply = fake_llm.json_reply(role, str(messages[-1].get("content") or ""), schema.__name__)
            return schema.model_validate(reply), gw.Usage()
        return await real_complete_json(self, role, messages, schema)

    gw.Gateway.complete_json = complete_json
    from voiceai.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
