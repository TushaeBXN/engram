"""Read-only summaries of the château for the web interface (``engram ui``).

Two views, both built from the files on disk and neither changing anything:

* :func:`overview`: every wing and room with its memory count, the totals,
  how many memories were saved on each recent day, and the newest memories.
* :func:`room`: the memories in one room, newest first, each with its
  status (current, superseded, disputed).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from engram.lineage import Lineage

SNIPPET = 280


def _statuses(chateau) -> tuple[dict, set]:
    """({superseded id: id that replaced it}, {disputed ids}) from the correction links."""
    replaced, disputed = {}, set()
    for link in Lineage(chateau.path).links():
        if link["kind"] == "supersedes":
            replaced[link["old"]] = link["new"]
        elif link["kind"] == "disputes":
            disputed.update((link["old"], link["new"]))
    return replaced, disputed - set(replaced)


def _brief(drawer, replaced: dict, disputed: set, chars: int = SNIPPET) -> dict:
    text = " ".join(drawer.text().split())
    status = "superseded" if drawer.id in replaced else ("disputed" if drawer.id in disputed else "current")
    out = {"id": drawer.id, "wing": drawer.wing, "room": drawer.room, "hall": drawer.hall,
           "timestamp": drawer.timestamp, "pinned": bool(drawer.pinned), "status": status,
           "source": drawer.source or "", "text": text[:chars], "truncated": len(text) > chars}
    if status == "superseded":
        out["superseded_by"] = replaced[drawer.id]
    return out


def _day(timestamp: str) -> str:
    try:
        ts = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date().isoformat()


def overview(chateau, days: int = 120, recent: int = 12) -> dict:
    """The whole château at a glance. One pass over the drawers."""
    replaced, disputed = _statuses(chateau)
    wings: dict[str, dict[str, dict]] = {}
    per_day: Counter = Counter()
    newest: list = []
    totals = Counter()
    for drawer in chateau.iter_drawers():
        room = wings.setdefault(drawer.wing, {}).setdefault(
            drawer.room, {"name": drawer.room, "memories": 0, "pinned": 0, "latest": "", "halls": Counter()})
        room["memories"] += 1
        room["halls"][drawer.hall] += 1
        room["pinned"] += bool(drawer.pinned)
        room["latest"] = max(room["latest"], drawer.timestamp or "")
        per_day[_day(drawer.timestamp)] += 1
        totals["memories"] += 1
        totals["pinned"] += bool(drawer.pinned)
        totals["superseded"] += drawer.id in replaced
        totals["disputed"] += drawer.id in disputed
        newest.append(drawer)
        if len(newest) > recent * 8:  # keep the list short while scanning
            newest = sorted(newest, key=lambda d: d.timestamp or "", reverse=True)[:recent]
    newest = sorted(newest, key=lambda d: d.timestamp or "", reverse=True)[:recent]
    today = datetime.now(timezone.utc).date()
    activity = [{"day": (today - timedelta(days=n)).isoformat(),
                 "count": per_day.get((today - timedelta(days=n)).isoformat(), 0)}
                for n in range(days - 1, -1, -1)]
    wing_list = []
    for name in sorted(wings):
        rooms = sorted(wings[name].values(), key=lambda r: (-r["memories"], r["name"]))
        for r in rooms:
            r["halls"] = dict(r["halls"])
        wing_list.append({"name": name, "memories": sum(r["memories"] for r in rooms), "rooms": rooms})
    return {
        "totals": {"wings": len(wing_list), "rooms": sum(len(w["rooms"]) for w in wing_list),
                   **{k: totals[k] for k in ("memories", "pinned", "superseded", "disputed")}},
        "wings": wing_list,
        "activity": activity,
        "recent": [_brief(d, replaced, disputed) for d in newest],
    }


def room(chateau, wing: str, name: str, limit: int = 200) -> dict:
    """The memories in one room, newest first."""
    replaced, disputed = _statuses(chateau)
    drawers = sorted(chateau.iter_drawers(wing=wing, room=name), key=lambda d: d.timestamp or "", reverse=True)
    return {"wing": wing, "room": name, "total": len(drawers),
            "memories": [_brief(d, replaced, disputed) for d in drawers[:limit]]}
