"""Registering the job handlers this service runs.

Spec: /architecture/jobs-and-events.md, /architecture/modular-structure.md

Registration is a decorator side effect, so it only happens if the owning module is imported.
Doing it here, from a declared list, means a lost import is a start-up error rather than a job
that retries to failure in silence (MOD-08).
"""
from __future__ import annotations

from voiceai.core import jobs


def install() -> None:
    jobs.install_handlers()
