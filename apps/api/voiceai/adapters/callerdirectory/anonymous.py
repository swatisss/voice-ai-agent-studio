"""Adapter: synthetic caller identities, derived from the seed and nothing else.

Spec: /architecture/evaluation.md

For deployments where running an evaluation must not read business records. The identities are
deterministic but fictitious, so a verification tool will reject them - which is correct for a
production evaluation harness and is why this is not the demo default.
"""
from __future__ import annotations

import hashlib

from voiceai.ports.callerdirectory import CallerProfile

FIRST = ("Alex", "Sam", "Jo", "Riley", "Casey", "Morgan", "Jordan", "Avery")
LAST = ("Carter", "Hayes", "Nolan", "Brooks", "Ellis", "Reed", "Shaw", "Quinn")


class AnonymousCallerDirectory:
    def profile_for(self, caller_ref: str | None, seed: str) -> CallerProfile | None:
        h = int(hashlib.md5((caller_ref or seed).encode()).hexdigest(), 16)
        return CallerProfile(
            name=f"{FIRST[h % len(FIRST)]} {LAST[(h // 8) % len(LAST)]}",
            member_id=f"{100000 + h % 900000}",
            date_of_birth=f"19{50 + h % 50}-{1 + h % 12:02d}-{1 + h % 28:02d}",
        )
