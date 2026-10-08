"""Control of live voice calls, behind the VoiceControl port.

Spec: /architecture/turn-detection.md (Live controls), /architecture/personas.md

The voice module drives the conversation brain, so it may name the conversation module and the
conversation module may not name it back (MOD-01). A route that changes a running call's persona or
turn detection therefore asks here, and is told when the call is not being served by this process.
"""
from __future__ import annotations

from voiceai.ports.voicecontrol import VoiceControl

__all__ = ["VoiceControl", "voice_control"]


def voice_control() -> VoiceControl:
    from voiceai.modules.voice.live_control import InProcessVoiceControl

    return InProcessVoiceControl()
