"""Content-based hall classification — local, deterministic, zero dependencies.

Miners used to pick a hall from the file extension or the speaker's role,
so "I prefer tabs over spaces" from a user message landed in ``facts`` and
"Root cause: the cache key ignored the tenant" from an assistant landed in
``discoveries`` only by coincidence.  This module scores the text itself
against a small set of phrase patterns per hall and returns the best match.

Nothing leaves the machine and no model is required.

Usage::

    hall, confidence = classify_hall("Turns out the bug was a race", fallback="facts")
"""

from __future__ import annotations

import re

from engram.chateau import HALL_TYPES

# Each pattern is worth one point; the hall with the most points wins.
_PATTERNS: dict[str, list[str]] = {
    "preferences": [
        r"\bi (?:really )?(?:prefer|like|love|hate|dislike|want)\b",
        r"\bwe (?:prefer|like|want)\b",
        r"\bi(?:'d| would) rather\b",
        r"\bmy (?:favou?rite|preference|preferred)\b",
        r"\b(?:always|never) (?:use|write|call|put)\b",
        r"\bdon'?t (?:like|want)\b",
        r"\bi'?m not a fan\b",
    ],
    "advice": [
        r"\byou (?:should|shouldn'?t|must|need to|might want to)\b",
        r"\b(?:i )?(?:recommend|suggest)\b",
        r"\bmake sure\b",
        r"\bbest practice\b",
        r"\b(?:tip|note|warning|gotcha):",
        r"\bavoid\b",
        r"\bdon'?t forget\b",
        r"\bconsider (?:using|adding|switching)\b",
        r"\bit'?s (?:better|safer) to\b",
    ],
    "events": [
        r"\b(?:yesterday|today|tonight|last (?:week|month|night|sprint)|this morning)\b",
        r"\b(?:shipped|deployed|released|launched|merged|migrated|rolled back)\b",
        r"\b(?:meeting|standup|stand-up|retro|incident|outage|demo)\b",
        r"\b(?:on|at|since) \d{4}-\d{2}-\d{2}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}\b",
    ],
    "discoveries": [
        r"\b(?:turns out|it turned out|found that|figured out|realized|realised|discovered)\b",
        r"\broot cause\b",
        r"\bthe (?:bug|issue|problem) (?:was|is)\b",
        r"\b(?:fixed|solved|resolved) (?:by|it by|with)\b",
        r"\b(?:learned|til)\b",
        r"\btraceback \(most recent call last\)",
        r"\bthe reason (?:was|is)\b",
    ],
    "facts": [
        r"\b(?:is|are) (?:located|stored|defined|configured) (?:in|at)\b",
        r"\buses? (?:postgres|mysql|sqlite|redis|python|node|rust|go)\b",
        r"\bthe (?:api|endpoint|port|url|database|schema) (?:is|for)\b",
    ],
}

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    hall: [re.compile(p, re.IGNORECASE) for p in pats] for hall, pats in _PATTERNS.items()
}

# Only look at the start of long texts: the opening usually carries the intent,
# and scanning a 500 KB file for keywords mostly produces noise.
_SCAN_CHARS = 4000


def score_halls(text: str) -> dict[str, int]:
    """Return the number of matching patterns for every hall."""
    sample = text[:_SCAN_CHARS]
    return {hall: sum(1 for p in pats if p.search(sample)) for hall, pats in _COMPILED.items()}


def classify_hall(text: str, fallback: str = "facts", min_score: int = 1) -> tuple[str, float]:
    """Pick the hall that best fits *text*.

    Args:
        text:       The content to classify.
        fallback:   Hall to use when nothing scores at least *min_score*
                    or when the top two halls tie.
        min_score:  Minimum number of matching patterns to override *fallback*.

    Returns:
        ``(hall, confidence)`` where confidence is the winner's share of all
        matched patterns (0.0 when the fallback was used).
    """
    if fallback not in HALL_TYPES:
        raise ValueError(f"Invalid fallback hall '{fallback}'. Choose from: {', '.join(HALL_TYPES)}")

    scores = score_halls(text)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, best_score), (_, runner_up) = ranked[0], ranked[1]

    if best_score < min_score or best_score == runner_up:
        return fallback, 0.0
    return best, round(best_score / sum(scores.values()), 2)
