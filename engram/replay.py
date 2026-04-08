"""Session replay — reconstruct the chronological story of a room.

Sorts all drawers in a room by timestamp and renders a narrative in plain
English using local ES decompression.  No API call required.

Usage::

    replayer = Replayer(palace)
    story = replayer.replay("auth-migration", wing="myapp")
    print(story)

CLI::

    engram replay --room auth-migration
    engram replay --room auth-migration --wing myapp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from engram.palace import Palace, Drawer
from engram.shorthand import decompress


class Replayer:
    """Reconstructs the chronological story of a room.

    Args:
        palace: The active Palace.
    """

    def __init__(self, palace: Palace) -> None:
        self.palace = palace

    # ------------------------------------------------------------------

    def replay(
        self,
        room: str,
        wing: Optional[str] = None,
        hall: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """Return a chronological narrative for *room*.

        Args:
            room:   Room name to replay.
            wing:   Optional wing filter.
            hall:   Optional hall type filter.
            limit:  Maximum number of drawers to include.

        Returns:
            A multi-line plain-English string.
        """
        drawers = list(self.palace.iter_drawers(wing=wing, room=room, hall=hall))
        if not drawers:
            return f"No memories found for room '{room}'" + (f" in wing '{wing}'" if wing else "") + "."

        # Sort chronologically
        drawers.sort(key=lambda d: _parse_ts(d.timestamp))
        drawers = drawers[:limit]

        # Group by hall for narrative structure
        lines = []
        header_parts = [f"Room: {room}"]
        if wing:
            header_parts.append(f"Wing: {wing}")
        lines.append("=" * 60)
        lines.append("  ".join(header_parts))
        lines.append(f"  {len(drawers)} memories  |  "
                     f"from {_fmt_ts(drawers[0].timestamp)} to {_fmt_ts(drawers[-1].timestamp)}")
        lines.append("=" * 60)
        lines.append("")

        for drawer in drawers:
            ts_str = _fmt_ts(drawer.timestamp)
            pin_marker = " 📌" if drawer.pinned else ""
            hall_label = drawer.hall.upper()
            text = decompress(drawer.content)
            # Wrap long lines
            if len(text) > 300:
                text = text[:297] + "..."
            lines.append(f"[{ts_str}] [{hall_label}]{pin_marker}")
            lines.append(f"  {text}")
            lines.append("")

        return "\n".join(lines)

    def replay_json(
        self,
        room: str,
        wing: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return replay data as a list of dicts (for MCP / JSON APIs)."""
        drawers = list(self.palace.iter_drawers(wing=wing, room=room))
        drawers.sort(key=lambda d: _parse_ts(d.timestamp))
        return [
            {
                "id": d.id,
                "timestamp": d.timestamp,
                "hall": d.hall,
                "content": decompress(d.content),
                "pinned": d.pinned,
            }
            for d in drawers[:limit]
        ]


# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16] if ts else "unknown"


if __name__ == "__main__":
    import sys
    room = sys.argv[1] if len(sys.argv) > 1 else "default"
    wing = sys.argv[2] if len(sys.argv) > 2 else None
    palace = Palace()
    replayer = Replayer(palace)
    print(replayer.replay(room, wing=wing))
