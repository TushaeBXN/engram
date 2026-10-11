"""Preference summaries for user messages.

People mention what they like, use, worry about or are working on in
passing ("I've been struggling with my sleep schedule lately, anyway..."),
and later ask questions that only make sense against it ("any tips for
getting more rest?"). A long message's embedding is dominated by its main
topic, so these asides are easy to miss. :func:`preference_summary` pulls
them out into a short extra text that is indexed alongside the message
(the stored drawer is never changed).

Usage::

    preference_summary("I prefer window seats. Can you book me a flight?")
    # -> "User has mentioned: window seats"
"""

from __future__ import annotations

import re
from typing import Optional

_SPAN = r"([^,.!?;\n]{5,80})"

PREFERENCE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\bi (?:really |also |generally |usually )?(?:prefer|like|love|enjoy) " + _SPAN,
    r"\bi(?:'m| am) (?:a big fan of|really into|into|fond of|allergic to) " + _SPAN,
    r"\bmy favou?rite " + _SPAN,
    r"\bi (?:usually|often|always|tend to|never) " + _SPAN,
    r"\bi (?:hate|dislike|can't stand|don't like|avoid) " + _SPAN,
    r"\bi(?:'ve| have) been (?:having (?:trouble|issues?|problems?) with|struggling with|dealing with) " + _SPAN,
    r"\bi(?:'ve| have) been (?:feeling|noticing|experiencing) " + _SPAN,
    r"\bi(?:'m| am|'ve been| have been) (?:worried|concerned|anxious) about " + _SPAN,
    r"\bi(?:'ve| have) been (?:trying|working on|focused on|focusing on|interested in|learning|practicing) " + _SPAN,
    r"\bi(?:'ve| have) been (?:considering|thinking about|planning) " + _SPAN,
    r"\bi(?:'m| am) (?:thinking about|thinking of|planning to|planning on|looking for|looking to|learning|trying to) " + _SPAN,
    r"\bi want to " + _SPAN,
    r"\bi(?:'m| am) (?:currently )?(?:using|working with|training for|studying) " + _SPAN,
    r"\bi (?:currently )?(?:use|own|drive|play) " + _SPAN,
    r"\bi used to " + _SPAN,
    r"\bi (?:still )?remember " + _SPAN,
    r"\b(?:lately|recently)[, ]+i(?:'ve been| have been|'m| am) " + _SPAN,
)]

MAX_MENTIONS = 12


def preference_mentions(text: str) -> list[str]:
    """Distinct preference/concern/intent phrases in *text*, in order of appearance."""
    found: list[tuple[int, str]] = []
    for pattern in PREFERENCE_PATTERNS:
        for m in pattern.finditer(text):
            found.append((m.start(), m.group(1).strip().rstrip(".,;!? ").lower()))
    seen: set[str] = set()
    mentions = []
    for _, phrase in sorted(found):
        if len(phrase) >= 5 and not any(phrase in kept for kept in seen):
            seen.add(phrase)
            mentions.append(phrase)
    return mentions[:MAX_MENTIONS]


def preference_summary(text: str) -> Optional[str]:
    """``"User has mentioned: a; b"`` for the phrases in *text*, or None if there are none."""
    mentions = preference_mentions(text)
    return "User has mentioned: " + "; ".join(mentions) if mentions else None
