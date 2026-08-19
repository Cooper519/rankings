"""Shared country exclusions for derived programme-discovery outputs."""

from __future__ import annotations

import re
from typing import Any


EXCLUDED_MAINLAND_CHINA_COUNTRY_LABELS = frozenset({
    "china",
    "china (mainland)",
    "mainland china",
    "people's republic of china",
    "pr china",
    "prc",
})


def normalize_country(value: Any) -> str:
    text = str(value or "").strip().casefold().replace("\u2019", "'")
    return re.sub(r"\s+", " ", text)


def is_mainland_china_country(value: Any) -> bool:
    """Return true only for mainland-China labels, not Hong Kong or Macau."""
    return normalize_country(value) in EXCLUDED_MAINLAND_CHINA_COUNTRY_LABELS
