"""The synthetic imagery shipped with this repository.

Spec: /architecture/imagery.md, /demo-data/evergreen-health.md

Two sets, and the difference is load-bearing:

* **samples** go through the ordinary look path - bounded, stored, described, pinned - and are
  tagged `sample` the whole way down, so a demo case can never pass as camera evidence (IMG-04,
  IMG-05).
* **references** are offered to a caller with no camera to narrow a report by description. They
  are never stored and never pinned, because nothing was looked at (IMG-02, IMG-03).

No image is generated at runtime. Not of the damage, not of an example, not of an avatar: a
product that can synthesise a convincing picture of a cracked footplate, inside the flow whose
output is an insurance case, is one careless prompt away from manufacturing its own evidence
(IMG-01).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ASSET_DIR = Path(__file__).with_name("assets")

#: Synthetic photographs of a specific fault, for the Test call page's sample path.
SAMPLES: dict[str, tuple[str, str]] = {
    "bed-rail": ("sample-bed-rail.jpg", "Bent bed side-rail"),
    "footplate": ("sample-footplate.jpg", "Cracked footplate"),
    "ceiling-tile": ("sample-ceiling-tile.jpg", "Water-stained ceiling tile"),
    "car-door": ("sample-car-door.jpg", "Dented car door"),
}

#: Neutral illustrations of a *kind* of fault, offered at most three at a time.
REFERENCES: dict[str, tuple[str, str]] = {
    "rail-bent": ("ref-rail-bent.jpg", "A side rail bent out of line"),
    "rail-snapped": ("ref-rail-snapped.jpg", "A side rail that will not latch"),
    "hoist-strap": ("ref-hoist-strap.jpg", "A frayed hoist strap"),
    "footplate-crack": ("ref-footplate-crack.jpg", "A cracked footplate"),
    "ceiling-stain": ("ref-ceiling-stain.jpg", "A water-stained ceiling tile"),
    "panel-dent": ("ref-panel-dent.jpg", "A dented panel"),
}

#: At most three are ever offered, so the caller is narrowing rather than browsing (IMG-02).
MAX_REFERENCES_OFFERED = 3


@lru_cache(maxsize=1)
def sample_images() -> dict[str, Path]:
    return {key: ASSET_DIR / filename for key, (filename, _label) in SAMPLES.items()}


@lru_cache(maxsize=1)
def reference_images() -> dict[str, Path]:
    return {key: ASSET_DIR / filename for key, (filename, _label) in REFERENCES.items()}


def sample_path(key: str) -> Path | None:
    path = sample_images().get(key)
    return path if path and path.is_file() else None


def sample_catalog() -> list[dict[str, str]]:
    """What the UI lists under "Synthetic demo images"."""
    return [{"key": key, "label": label} for key, (_f, label) in SAMPLES.items()]


def reference_catalog(limit: int = MAX_REFERENCES_OFFERED) -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, (_f, label) in list(REFERENCES.items())[:limit]]
