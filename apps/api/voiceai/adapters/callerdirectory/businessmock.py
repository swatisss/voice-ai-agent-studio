"""Adapter: simulated callers drawn from the demo business dataset.

Spec: /architecture/evaluation.md, /demo-data/members-and-claims.md

The demo default, so an evaluation transcript names people a reviewer recognises from the seeded
data. Fleet learning used to reach into this dataset itself; now it asks a port and this adapter is
a configuration choice, which is what keeps production evaluation independent of demo fixtures.
"""
from __future__ import annotations

import hashlib

from voiceai.ports.callerdirectory import CallerProfile


class BusinessMockCallerDirectory:
    def profile_for(self, caller_ref: str | None, seed: str) -> CallerProfile | None:
        from voiceai.modules.businessmock import data

        members = data.MEMBERS
        if caller_ref not in members:  # deterministic in seed, so a run can be repeated
            refs = sorted(members)
            if not refs:
                return None
            caller_ref = refs[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(refs)]
        m = members[caller_ref]
        return CallerProfile(
            name=f"{m['first_name']} {m['last_name']}",
            member_id=caller_ref.split("-")[1],
            date_of_birth=m["dob"],
        )
