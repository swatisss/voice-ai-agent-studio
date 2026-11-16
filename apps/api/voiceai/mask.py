"""Masking of identifiers: member references, emails, telephone numbers and long digit runs.

Spec: /architecture/agent-desk.md (Masking)
"""
from __future__ import annotations

import logging
import re
from typing import Any

DOT = "•"
# Ids that look like `AB-123456` but are not member references (prior-auth, claim, policy, quote, retry ... ids).
NOT_MEMBER = {"PA", "CL", "PMI", "CC", "CSH", "UW", "RT", "GPB", "QT", "EV"}

_REF = re.compile(r"(?<![\w-])([A-Z]{2,5})-(\d{6})(?![\w-])")
_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-])[\w.+-]*@([\w-]+(?:\.[\w-]+)+)")
_PHONE = re.compile(r"(?<![\w-])\+?\d[\d ()-]{7,}\d(?![\w-])")
_DIGITS = re.compile(r"(?<![\w.:+-])\d{6,}(?![\w.:-])")  # not the fraction of a time or a decimal
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")


def member_ref(ref: str | None) -> str | None:
    """`NGH-410237` -> `NGH-•••237`; a reference with no dash keeps only its last three characters."""
    if not ref:
        return ref
    head, sep, tail = ref.rpartition("-")
    return f"{head}-{DOT * 3}{tail[-3:]}" if sep else f"{DOT * 3}{ref[-3:]}"


def phone(number: str | None) -> str | None:
    """`+447700900123` -> `•••0123`."""
    digits = re.sub(r"\D", "", number or "")
    return f"{DOT * 3}{digits[-4:]}" if digits else number


def email(address: str | None) -> str | None:
    """`meera@example.com` -> `m***@example.com`."""
    if not address or "@" not in address:
        return address
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def _phone_sub(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return phone(m.group(0)) or "" if len(digits) >= 9 else m.group(0)  # a date or a short number is not a telephone number


def _mask_plain(value: str) -> str:
    out = _REF.sub(lambda m: m.group(0) if m.group(1) in NOT_MEMBER else f"{m.group(1)}-{DOT * 3}{m.group(2)[-3:]}", value)
    out = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", out)
    out = _PHONE.sub(_phone_sub, out)
    return _DIGITS.sub(lambda m: f"{DOT * 3}{m.group(0)[-3:]}", out)


def text(value: str) -> str:
    """Mask identifiers anywhere in free text. Best effort: hides identifiers, not names or health details.

    A timestamp (`2026-11-16T15:34:17.123276+00:00`) is never an identifier and is left exactly as it is.
    """
    if not value:
        return value
    parts, last = [], 0
    for m in _ISO.finditer(value):
        parts += [_mask_plain(value[last:m.start()]), m.group(0)]
        last = m.end()
    return "".join(parts) + _mask_plain(value[last:])


def walk(data: Any) -> Any:
    """`text()` on every string value of a JSON-like structure (keys are left alone)."""
    if isinstance(data, str):
        return text(data)
    if isinstance(data, list):
        return [walk(v) for v in data]
    if isinstance(data, dict):
        return {k: walk(v) for k, v in data.items()}
    return data


_installed = False


def install_log_filter() -> None:
    """Mask the message of every record from a `voiceai.*` logger, whatever handler prints it (DESK-07)."""
    global _installed
    if _installed:
        return
    _installed = True
    make = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = make(*args, **kwargs)
        if record.name == "voiceai" or record.name.startswith("voiceai."):
            try:
                record.msg, record.args = text(record.getMessage()), None
            except Exception:  # noqa: BLE001  # a bad format string must never break logging
                pass
        return record

    logging.setLogRecordFactory(factory)
