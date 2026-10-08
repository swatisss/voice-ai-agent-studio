"""Caller identities for evaluation, behind the CallerDirectory port.

Spec: /architecture/evaluation.md

`EVAL_CALLER_DIRECTORY` chooses the adapter. It defaults to the demo dataset so seeded evaluations
read as they always have; a deployment that must not touch business records to run an evaluation
sets `anonymous`.
"""
from __future__ import annotations

from voiceai.adapters.callerdirectory.anonymous import AnonymousCallerDirectory
from voiceai.adapters.callerdirectory.businessmock import BusinessMockCallerDirectory
from voiceai.core.config import get_settings
from voiceai.ports.callerdirectory import CallerDirectory, CallerProfile

__all__ = ["CallerDirectory", "CallerProfile", "caller_directory"]

ADAPTERS = {"businessmock": BusinessMockCallerDirectory, "anonymous": AnonymousCallerDirectory}


def caller_directory() -> CallerDirectory:
    name = get_settings().eval_caller_directory
    return ADAPTERS.get(name, BusinessMockCallerDirectory)()
