"""Design tokens meet WCAG AA contrast. Covers: UI-18"""
from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[3] / "apps" / "web" / "app" / "globals.css"
PAIRS = [
    ("text", "bg"), ("text", "panel"), ("text", "neutral-soft"), ("muted", "bg"), ("muted", "panel"), ("muted", "neutral-soft"),
    ("accent", "panel"), ("accent", "bg"), ("accent", "accent-soft"), ("on-accent", "accent"),
    ("ok", "ok-soft"), ("warn", "warn-soft"), ("bad", "bad-soft"), ("info", "info-soft"),
]


def _tokens(block: str) -> dict[str, str]:
    return {k: v.upper() for k, v in re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", block)}


def _blocks() -> tuple[dict[str, str], dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    light = _tokens(css.split("@media (prefers-color-scheme: dark)")[0])
    dark = _tokens(css.split("@media (prefers-color-scheme: dark)")[1].split("@theme")[0])
    return light, dark


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_pair_meets_aa_in_light_and_dark():
    """Covers: UI-18"""
    light, dark = _blocks()
    for name, tokens in (("light", light), ("dark", dark)):
        failures = [(fg, bg, round(contrast(tokens[fg], tokens[bg]), 2)) for fg, bg in PAIRS if contrast(tokens[fg], tokens[bg]) < 4.5]
        assert not failures, f"{name} mode pairs below 4.5:1: {failures}"


def test_spec_table_matches_css():
    """The documented token values are the real ones."""
    spec = (Path(__file__).resolve().parents[3] / "specs" / "ui" / "design-system.md").read_text(encoding="utf-8")
    light, dark = _blocks()
    for name in ("bg", "panel", "text", "muted", "accent", "on-accent", "accent-soft", "neutral-soft"):
        assert light[name] in spec.upper() and dark[name] in spec.upper(), name
