"""Post-call analysis, behind the PostCallAnalysis port.

Spec: /architecture/fleet-learning.md, /architecture/modular-structure.md

Looked up here rather than imported directly, so that the conversation and hand-off modules never
name fleet learning: learning names them (it drives simulated calls and reads transcripts), and the
module graph has to stay acyclic.
"""
from __future__ import annotations

from voiceai.ports.postcall import PostCallAnalysis, Trigger

__all__ = ["PostCallAnalysis", "Trigger", "post_call_analysis"]


def post_call_analysis() -> PostCallAnalysis:
    from voiceai.modules.learning.postcall import LearningPostCallAnalysis

    return LearningPostCallAnalysis()
