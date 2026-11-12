#!/usr/bin/env python3
"""Load an agent's use cases from a Markdown file: one `## Title` section per use case.

    python scripts/import_use_cases.py --agent "Dental Care agent" --file scripts/demo/dental/use-cases.md
    python scripts/import_use_cases.py --agent "Dental Care agent" --file my-use-cases.md --replace   # also delete the others
    python scripts/import_use_cases.py --file scripts/demo/dental/use-cases.md --dry-run               # parse and print only

The file format (frontmatter optional; `category` there is the default for every use case):

    ---
    category: Dental care
    ---
    ## Book an appointment
    Existing patients verify, new patients register; offer slots, read back, book.

    Channels: voice, chat
    Sample phrases:
    - I'd like to book a check-up at the Leeds practice.
    - I'm new, can I register?
    Demo callers:
    - Priya Shah | OD-10231 | 12 April 1988 | Book a hygiene appointment in Leeds next week

Use cases are matched by title: existing ones are updated, new ones added. It uses the same REST API as the Use cases
tab (/api/rest-api.md, Use cases), so routing updates right away, exactly as when they are typed in. Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

CHANNELS = {"voice", "chat", "phone"}


def parse(text: str) -> list[dict[str, Any]]:
    """The use cases in the file, validated like the API (title 3-120, summary <= 600, 1-20 phrases of 3-200 characters)."""
    default_category = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        for line in text[3:end].splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "category":
                default_category = value.strip()
        text = text[end + 4:]
    out: list[dict[str, Any]] = []
    for block in re.split(r"^## +", text, flags=re.M)[1:]:
        lines = block.splitlines()
        uc: dict[str, Any] = {"title": lines[0].strip(), "summary": "", "category": default_category,
                              "channels": ["voice", "chat"], "sample_utterances": [], "demo_callers": []}
        section, summary = None, []
        for raw in lines[1:]:
            line = raw.strip()
            low = line.lower()
            if not line:
                continue
            if low.startswith("category:"):
                uc["category"] = line.split(":", 1)[1].strip()
            elif low.startswith("channels:"):
                uc["channels"] = [c.strip().lower() for c in line.split(":", 1)[1].split(",") if c.strip()]
            elif low.rstrip(":") in ("sample phrases", "samples", "sample utterances"):
                section = "samples"
            elif low.rstrip(":") in ("demo callers", "callers"):
                section = "callers"
            elif line[:2] in ("- ", "* ") and section == "samples":
                uc["sample_utterances"].append(line[2:].strip().strip('"'))
            elif line[:2] in ("- ", "* ") and section == "callers":
                parts = [p.strip() for p in line[2:].split("|")]
                uc["demo_callers"].append(dict(zip(("name", "member_id", "date_of_birth", "try"), parts + [""] * (4 - len(parts)))))
            else:
                summary.append(line)
        uc["summary"] = " ".join(summary)
        problems = [p for p, bad in (
            ("title must be 3-120 characters", not 3 <= len(uc["title"]) <= 120),
            ("summary is over 600 characters", len(uc["summary"]) > 600),
            ("needs 1-20 sample phrases", not 1 <= len(uc["sample_utterances"]) <= 20),
            ("each sample phrase must be 3-200 characters", any(not 3 <= len(u) <= 200 for u in uc["sample_utterances"])),
            (f"channels must be among {sorted(CHANNELS)}", not uc["channels"] or not set(uc["channels"]) <= CHANNELS)) if bad]
        if problems:
            raise ValueError(f"use case {uc['title']!r}: " + "; ".join(problems))
        out.append(uc)
    if not out:
        raise ValueError("no use cases found: start each one with a '## Title' line")
    return out


def load(path: Path) -> list[dict[str, Any]]:
    return parse(path.read_text(encoding="utf-8"))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", required=True, type=Path, help="the use-cases Markdown file")
    ap.add_argument("--agent", help="agent name (as shown in the Agents list) or id")
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL (default http://127.0.0.1:8000; on Windows \"localhost\" tries IPv6 first and costs ~2 s a request)")
    ap.add_argument("--tenant", default="evergreen-care", help="business unit of the agent (default evergreen-care)")
    ap.add_argument("--replace", action="store_true", help="also delete the agent's use cases that are not in the file")
    ap.add_argument("--dry-run", action="store_true", help="parse and print, change nothing")
    args = ap.parse_args()
    try:
        cases = load(args.file)
    except (OSError, ValueError) as exc:
        print(f"Cannot read {args.file}: {exc}")
        return 1
    if args.dry_run or not args.agent:
        for uc in cases:
            print(f"- {uc['title']} [{uc['category'] or 'no category'}; {', '.join(uc['channels'])}]: "
                  f"{len(uc['sample_utterances'])} phrase(s), {len(uc['demo_callers'])} demo caller(s)")
        print(f"{len(cases)} use case(s) parsed" + ("" if args.agent else "; give --agent to load them"))
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from demo_walkthrough import Api, ApiError, studio_passwords

    api = Api(args.api, args.tenant)
    try:
        if (api.get("/api/auth/me") or {}).get("enabled"):
            api.login("admin@echomind.test", studio_passwords(False)["admin"])
        agents = api.get("/api/agents")["items"]
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot reach {args.api} as the admin: {exc}. Is the stack running (python scripts/dev.py)?")
        return 1
    agent = next((a for a in agents if args.agent in (a["id"], a["name"])), None)
    if agent is None:
        print(f"No agent {args.agent!r} in business unit {args.tenant}. Agents there: {', '.join(a['name'] for a in agents)}")
        return 1
    existing = {u["title"]: u for u in api.get(f"/api/use-cases?agent_id={agent['id']}")["items"]}
    added = updated = deleted = 0
    try:
        for n, uc in enumerate(cases):
            if uc["title"] in existing:
                api.put(f"/api/use-cases/{existing[uc['title']]['id']}", {**uc, "sort": n})
                updated += 1
            else:
                api.post("/api/use-cases", {**uc, "agent_id": agent["id"], "sort": n})
                added += 1
        if args.replace:
            for title, u in existing.items():
                if title not in {c["title"] for c in cases}:
                    api.call("DELETE", f"/api/use-cases/{u['id']}")
                    deleted += 1
    except ApiError as exc:
        print(f"The API refused a use case: {exc.body}")
        return 1
    print(f"{agent['name']}: {added} added, {updated} updated" + (f", {deleted} deleted" if args.replace else "")
          + ". Reload the Use cases tab to see them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
