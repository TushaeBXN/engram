"""Time references in queries: "3 weeks ago", "last month", "in June", "on 8 May 2023".

When a query says *when* something happened, memories stored around that
date are better candidates than equally similar ones from another time.
:func:`time_reference` turns the phrase into ``(days_back, tolerance_days)``,
and :func:`temporal_closeness` scores how near a memory's timestamp is to
the date it points at.

Usage::

    ref = time_reference("what did I buy two weeks ago?")   # (14, 5)
    ref = time_reference("what happened in June?", now)     # days back to mid-June, ±16
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


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s*((?:19|20)\d{2}))?"
# "May 8(, 2023)", "8 May (2023)", "in/on/during/since/... June (2023)", "in 2022"
_MONTH_DAY = re.compile(r"\b" + _MON + r"\s+" + _DAY + r"\b" + _YEAR)
_DAY_MONTH = re.compile(r"\b" + _DAY + r"(?:\s+of)?\s+" + _MON + r"\b" + _YEAR)
_IN_MONTH = re.compile(r"\b(?:in|on|during|since|around|by|from|of|early|late|mid|until)\s+(?:early\s+|late\s+|mid\s+)?"
                       + _MON + r"\b" + _YEAR)
_IN_YEAR = re.compile(r"\b(?:in|during|since|of|around)\s+((?:19|20)\d{2})\b")


def _days_back(now: datetime, year: Optional[int], month: int, day: int, tolerance: int):
    """``(days_back, tolerance)`` to the given date; the most recent such date
    when no year is given. None for an impossible date or one in the future."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        target = datetime(year or now.year, month, day, 12, tzinfo=timezone.utc)
    except ValueError:
        return None
    if year is None and target > now:
        try:
            target = target.replace(year=now.year - 1)
        except ValueError:
            return None
    days = (now - target).days
    return (days, tolerance) if days >= 0 else None


def _absolute_reference(q: str, now: datetime) -> Optional[tuple[int, int]]:
    for pattern, day_first in ((_MONTH_DAY, False), (_DAY_MONTH, True)):
        m = pattern.search(q)
        if m:
            day, month = (m.group(1), m.group(2)) if day_first else (m.group(2), m.group(1))
            year = int(m.group(3)) if m.group(3) else None
            ref = _days_back(now, year, _MONTHS[month.rstrip(".")], int(day), 2)
            if ref:
                return ref
    m = _IN_MONTH.search(q)
    if m:
        year = int(m.group(2)) if m.group(2) else None
        ref = _days_back(now, year, _MONTHS[m.group(1).rstrip(".")], 15, 16)
        if ref:
            return ref
    m = _IN_YEAR.search(q)
    if m:
        return _days_back(now, int(m.group(1)), 7, 1, 183)
    return None


def time_reference(query: str, now: Optional[datetime] = None) -> Optional[tuple[int, int]]:
    """Return ``(days_back, tolerance_days)`` for the first time phrase in *query*.

    Relative phrases ("5 days ago", "a couple of weeks ago", "last month",
    "yesterday") always work. Dates ("on May 8", "8 May 2023", "in June",
    "in 2022") are understood when *now* is given, counted back from it; a
    date without a year means its most recent occurrence. Anything else
    returns None.
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
    if now is not None:
        return _absolute_reference(q, now)
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
