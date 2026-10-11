"""Time references in queries: "3 weeks ago", "last month", "yesterday".

When a query says *when* something happened, memories stored around that
date are better candidates than equally similar ones from another time.
:func:`time_reference` turns the phrase into ``(days_back, tolerance_days)``,
and :func:`temporal_closeness` scores how near a memory's timestamp is to
the date it points at.

Usage::

    ref = time_reference("what did I buy two weeks ago?")   # (14, 5)
    closeness = temporal_closeness(drawer_timestamp, now, ref)  # 0.0 - 1.0
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "a couple of": 2, "a couple": 2, "couple of": 2, "a few": 3, "few": 3, "several": 4,
}
_NUM = r"(\d+|a couple of|a couple|couple of|a few|few|several|an|a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"

_AGO = re.compile(r"\b" + _NUM + r"\s+(day|week|month|year)s?\s+ago\b")
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

# Fixed phrases: (pattern, days back, tolerance in days)
_FIXED = [
    (re.compile(r"\bday before yesterday\b"), 2, 1),
    (re.compile(r"\byesterday\b"), 1, 1),
    (re.compile(r"\blast week(?:end)?\b"), 7, 3),
    (re.compile(r"\bearlier this week\b"), 3, 3),
    (re.compile(r"\blast month\b"), 30, 7),
    (re.compile(r"\bearlier this month\b"), 14, 10),
    (re.compile(r"\blast year\b"), 365, 30),
]


def time_reference(query: str) -> Optional[tuple[int, int]]:
    """Return ``(days_back, tolerance_days)`` for the first time phrase in *query*.

    Only relative phrases are understood ("5 days ago", "a couple of weeks
    ago", "last month", "yesterday"); anything else returns None.
    """
    q = query.lower()
    m = _AGO.search(q)
    if m:
        count = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1)]
        unit = _UNIT_DAYS[m.group(2)]
        days = count * unit
        # Wider windows for coarser units: "3 months ago" is rarely exact.
        tolerance = {1: 2, 7: 5, 30: 10, 365: 30}[unit]
        return days, tolerance
    for pattern, days, tolerance in _FIXED:
        if pattern.search(q):
            return days, tolerance
    return None


def temporal_closeness(timestamp: str, now: datetime, ref: tuple[int, int]) -> float:
    """How close *timestamp* is to ``now - days_back``: 1.0 inside the tolerance,
    falling linearly to 0.0 at three times the tolerance. Unparseable or
    missing timestamps score 0.0."""
    if not timestamp:
        return 0.0
    try:
        ts = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days_back, tolerance = ref
    delta = abs((ts - (now - timedelta(days=days_back))).total_seconds()) / 86400
    if delta <= tolerance:
        return 1.0
    if delta <= tolerance * 3:
        return 1.0 - (delta - tolerance) / (tolerance * 2)
    return 0.0
