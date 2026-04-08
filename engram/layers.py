"""L0–L3 memory stack — context layers loaded into AI sessions.

Layer  Content                            Size      When Loaded
───────────────────────────────────────────────────────────────
L0     Identity — who is this AI?         ~50 tok   Always
L1     Critical facts in ES               ~120 tok  Always
L2     Room recall — current project      On demand  When topic arises
L3     Deep semantic search               On demand  Explicit query

Total cold-start context: ~170 tokens (L0 + L1 only).

Usage::

    stack = LayerStack(palace, searcher)
    context = stack.wake_up(wing="myapp")   # → L0 + L1 text
    room_ctx = stack.load_room("myapp", "auth-migration")  # → L2
    deep = stack.deep_search("auth migration", wing="myapp")  # → L3
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from engram.palace import Palace, HALL_TYPES
from engram.searcher import Searcher
from engram.shorthand import compress, decompress
from engram.config import get_identity, ENGRAM_DIR, load_config

_L1_PATH = ENGRAM_DIR / "l1_facts.es"


class LayerStack:
    """Manages the four memory layers for AI context injection.

    Args:
        palace:   The active Palace.
        searcher: Initialised Searcher.
        config:   Config dict.
    """

    def __init__(
        self, palace: Palace, searcher: Searcher, config: Optional[dict] = None
    ) -> None:
        self.palace = palace
        self.searcher = searcher
        self.config = config or load_config()

    # ------------------------------------------------------------------
    # L0 — identity
    # ------------------------------------------------------------------

    def l0(self) -> str:
        """Return the L0 identity block (~50 tokens)."""
        identity = get_identity()
        if not identity:
            return "[L0] No identity set. Run `engram init` to configure."
        return f"[L0:identity]\n{identity}"

    def set_identity(self, text: str) -> None:
        """Write the L0 identity file."""
        from engram.config import IDENTITY_PATH, ensure_engram_dir
        ensure_engram_dir()
        IDENTITY_PATH.write_text(text.strip())

    # ------------------------------------------------------------------
    # L1 — critical facts
    # ------------------------------------------------------------------

    def l1(self) -> str:
        """Return the L1 critical facts block (~120 tokens in ES)."""
        if _L1_PATH.exists():
            return f"[L1:facts]\n{_L1_PATH.read_text().strip()}"
        return "[L1] No critical facts set. Run `engram wake-up` to generate."

    def rebuild_l1(self, wing: Optional[str] = None, n: int = 20) -> str:
        """Regenerate L1 from the most recent/pinned facts hall drawers."""
        lines = []
        for drawer in self.palace.iter_drawers(wing=wing, hall="facts"):
            if drawer.pinned or drawer.age_days() < 30:
                lines.append(drawer.content)
            if len(lines) >= n:
                break
        if not lines:
            content = "No critical facts available."
        else:
            content = compress("\n".join(lines[:n]))
        _L1_PATH.parent.mkdir(parents=True, exist_ok=True)
        _L1_PATH.write_text(content)
        return content

    # ------------------------------------------------------------------
    # L2 — room recall
    # ------------------------------------------------------------------

    def load_room(self, wing: str, room: str) -> str:
        """Load the L2 context for a specific room (closets for all halls)."""
        parts = [f"[L2:room={wing}/{room}]"]
        for hall in HALL_TYPES:
            closet = self.palace.get_closet(wing, room, hall)
            if closet and closet.content.strip():
                parts.append(f"  [{hall}] {closet.content.strip()}")
        if len(parts) == 1:
            parts.append("  (no closet content — run `engram compress` to build)")
        return "\n".join(parts)

    def load_room_drawers(self, wing: str, room: str, n: int = 10) -> str:
        """Load raw drawer content for a room (more verbose than closets)."""
        parts = [f"[L2:room={wing}/{room}:raw]"]
        drawers = list(self.palace.iter_drawers(wing=wing, room=room))
        drawers.sort(key=lambda d: d.timestamp, reverse=True)
        for drawer in drawers[:n]:
            parts.append(f"  [{drawer.hall}] {drawer.content[:300]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # L3 — deep search
    # ------------------------------------------------------------------

    def deep_search(
        self,
        query: str,
        wing: Optional[str] = None,
        n: int = 5,
    ) -> str:
        """Run semantic search and return formatted L3 context block."""
        results = self.searcher.search(query, n=n, wing=wing)
        if not results:
            return f"[L3:search='{query}']\n  No results found."
        parts = [f"[L3:search='{query}']"]
        for i, r in enumerate(results, 1):
            meta = r.get("metadata", {})
            loc = f"{meta.get('wing', '?')}/{meta.get('room', '?')}/{meta.get('hall', '?')}"
            score = r.get("final_score", 0.0)
            text = r.get("text", "")[:200]
            parts.append(f"  [{i}|{loc}|score={score:.3f}] {text}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Wake-up (L0 + L1)
    # ------------------------------------------------------------------

    def wake_up(self, wing: Optional[str] = None, rebuild_l1: bool = False) -> str:
        """Return the cold-start context block (L0 + L1, ~170 tokens)."""
        if rebuild_l1:
            self.rebuild_l1(wing=wing)
        return f"{self.l0()}\n\n{self.l1()}"


if __name__ == "__main__":
    from engram.palace import Palace
    from engram.backends import get_backend
    cfg = load_config()
    palace = Palace()
    backend = get_backend(cfg["vector_backend"])
    searcher = Searcher(backend, palace, cfg)
    stack = LayerStack(palace, searcher, cfg)
    print(stack.wake_up())
