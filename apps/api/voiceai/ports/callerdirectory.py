"""Port: identities for simulated callers.

Spec: /architecture/evaluation.md

Evaluation needs a plausible person for the simulated caller to be. It used to import the demo
business dataset directly, which made production evaluation depend on demo fixtures. Behind this
port that is a configuration choice: the demo keeps using recognisable members, a real deployment
uses synthetic identities and never reads business data to run an evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CallerProfile:
    name: str
    member_id: str
    date_of_birth: str
    extra: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class CallerDirectory(Protocol):
    def profile_for(self, caller_ref: str | None, seed: str) -> CallerProfile | None:
        """A profile for this caller, or None when none is available. MUST be deterministic in
        `seed` so an evaluation can be repeated."""
        ...
