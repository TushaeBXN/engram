"""Room navigation graph — models which rooms are connected via tunnels.

Provides a simple adjacency-list graph over the château's wings and rooms,
enabling navigation and link suggestions.

Usage::

    graph = PalaceGraph(palace)
    graph.build()
    neighbours = graph.neighbours("auth-migration")
    graph.suggest_links()
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from engram.palace import Palace


class PalaceGraph:
    """Builds an in-memory navigation graph over the château.

    Nodes are (wing, room) tuples.  Edges are Tunnels.

    Args:
        palace: The active Palace.
    """

    def __init__(self, palace: Palace) -> None:
        self.palace = palace
        self._adj: dict[str, list[str]] = defaultdict(list)  # room → [room]
        self._built = False

    def build(self) -> None:
        """Scan all wings and construct the adjacency list."""
        self._adj.clear()
        for wing in self.palace.list_wings():
            for tunnel in self.palace.list_tunnels(wing.name):
                a = tunnel.room
                b = tunnel.target_wing
                if b not in self._adj[a]:
                    self._adj[a].append(b)
                if a not in self._adj[b]:
                    self._adj[b].append(a)
        self._built = True

    def neighbours(self, room: str) -> list[str]:
        """Return rooms connected to *room* via tunnels."""
        if not self._built:
            self.build()
        return list(self._adj.get(room, []))

    def suggest_links(self, min_rooms: int = 2) -> list[dict]:
        """Suggest rooms that appear in multiple wings but have no tunnel.

        Returns a list of suggestions::

            [{"room": str, "wings": [str, ...]}]
        """
        if not self._built:
            self.build()
        # Find rooms appearing in >1 wing
        room_wings: dict[str, list[str]] = defaultdict(list)
        for wing in self.palace.list_wings():
            for room in self.palace.list_rooms(wing.name):
                room_wings[room.name].append(wing.name)

        suggestions = []
        for room, wings in room_wings.items():
            if len(wings) >= min_rooms and room not in self._adj:
                suggestions.append({"room": room, "wings": wings})
        return suggestions

    def all_rooms(self) -> list[tuple[str, str]]:
        """Return all (wing, room) tuples in the château."""
        pairs = []
        for wing in self.palace.list_wings():
            for room in self.palace.list_rooms(wing.name):
                pairs.append((wing.name, room.name))
        return pairs


if __name__ == "__main__":
    palace = Palace()
    graph = PalaceGraph(palace)
    graph.build()
    print("All rooms:", graph.all_rooms())
    print("Suggested links:", graph.suggest_links())
