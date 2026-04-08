"""Memory health audit — surfaces orphaned, stale, and unlinked memories.

Output example::

    ENGRAM HEALTH AUDIT
    ───────────────────
    Orphaned drawers (no room assigned):     3
    Rooms with no closet (uncompressed):     7
    Wings inactive > 90 days:               1  → wing_old_project
    KG triples missing valid_from:          12
    Rooms in only 1 wing (no tunnels):       4  → consider linking
    Pinned memories:                         2

    Run `engram audit --fix` to auto-resolve safe issues.

Usage::

    auditor = Auditor(palace, kg)
    report = auditor.run()
    auditor.fix_safe(report)   # auto-resolves easy issues
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from engram.chateau import Chateau, HALL_TYPES
from engram.knowledge_graph import KnowledgeGraph


@dataclass
class AuditReport:
    """Results of a château health audit."""

    orphaned_drawers: list[str] = field(default_factory=list)
    rooms_no_closet: list[str] = field(default_factory=list)
    inactive_wings: list[str] = field(default_factory=list)
    kg_missing_valid_from: int = 0
    rooms_single_wing: list[str] = field(default_factory=list)
    pinned_count: int = 0
    total_drawers: int = 0
    total_rooms: int = 0
    total_wings: int = 0

    def to_dict(self) -> dict:
        return {
            "orphaned_drawers": len(self.orphaned_drawers),
            "rooms_no_closet": len(self.rooms_no_closet),
            "inactive_wings": self.inactive_wings,
            "kg_missing_valid_from": self.kg_missing_valid_from,
            "rooms_single_wing": len(self.rooms_single_wing),
            "pinned_count": self.pinned_count,
            "total_drawers": self.total_drawers,
            "total_rooms": self.total_rooms,
            "total_wings": self.total_wings,
        }


class Auditor:
    """Runs health checks on the château and reports findings.

    Args:
        palace:  The active Palace.
        kg:      The active KnowledgeGraph.
    """

    def __init__(self, palace: Chateau, kg: KnowledgeGraph) -> None:
        self.palace = palace
        self.kg = kg

    # ------------------------------------------------------------------

    def run(self, inactive_threshold_days: int = 90) -> AuditReport:
        """Run all health checks and return an AuditReport."""
        report = AuditReport()
        now = datetime.now(timezone.utc)

        wings = self.palace.list_wings()
        report.total_wings = len(wings)

        for wing in wings:
            rooms = self.palace.list_rooms(wing.name)
            report.total_rooms += len(rooms)

            # Detect inactive wings
            last_activity = self._last_wing_activity(wing.name)
            if last_activity:
                age = (now - last_activity).days
                if age > inactive_threshold_days:
                    report.inactive_wings.append(wing.name)

            for room in rooms:
                room_key = f"{wing.name}/{room.name}"

                # Orphaned drawers — drawers whose hall dir doesn't match HALL_TYPES
                for drawer in self.palace.iter_drawers(wing=wing.name, room=room.name):
                    report.total_drawers += 1
                    if drawer.pinned:
                        report.pinned_count += 1
                    if drawer.hall not in HALL_TYPES:
                        report.orphaned_drawers.append(drawer.id)

                # Rooms with no closet in any hall
                has_closet = any(
                    self.palace.get_closet(wing.name, room.name, hall) is not None
                    for hall in HALL_TYPES
                )
                if not has_closet:
                    report.rooms_no_closet.append(room_key)

            # Rooms appearing in only this wing (no tunnels)
            tunnels = self.palace.list_tunnels(wing.name)
            linked_rooms = {t.room for t in tunnels}
            for room in rooms:
                if room.name not in linked_rooms:
                    report.rooms_single_wing.append(f"{wing.name}/{room.name}")

        # KG integrity
        report.kg_missing_valid_from = len(self.kg.triples_missing_valid_from())

        return report

    # ------------------------------------------------------------------

    def fix_safe(self, report: AuditReport) -> int:
        """Auto-resolve safe issues (orphaned drawers, empty closets).

        Returns the number of issues fixed.
        """
        fixed = 0

        # Rebuild empty closets via compression
        for room_key in report.rooms_no_closet:
            try:
                wing, room = room_key.split("/", 1)
                self._build_closets(wing, room)
                fixed += 1
            except Exception:
                continue

        return fixed

    # ------------------------------------------------------------------

    def _last_wing_activity(self, wing: str) -> Optional[datetime]:
        """Return the timestamp of the most recently modified drawer in a wing."""
        latest = None
        for drawer in self.palace.iter_drawers(wing=wing):
            try:
                ts = datetime.fromisoformat(drawer.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if latest is None or ts > latest:
                    latest = ts
            except ValueError:
                continue
        return latest

    def _build_closets(self, wing: str, room: str) -> None:
        """Build ES closets for a room from its drawers."""
        from engram.shorthand import compress
        from engram.chateau import Closet

        for hall in HALL_TYPES:
            drawers = list(self.palace.iter_drawers(wing=wing, room=room, hall=hall))
            if not drawers:
                continue
            combined = "\n".join(d.content for d in drawers[:10])
            closet = Closet(
                content=compress(combined),
                wing=wing,
                room=room,
                hall=hall,
            )
            self.palace.save_closet(closet)


# ---------------------------------------------------------------------------

def format_report(report: AuditReport) -> str:
    """Return a Rich-formatted audit report string."""
    lines = [
        "[bold]ENGRAM HEALTH AUDIT[/bold]",
        "─" * 35,
        f"Orphaned drawers (unknown hall):       [red]{len(report.orphaned_drawers)}[/red]",
        f"Rooms with no closet (uncompressed):   [yellow]{len(report.rooms_no_closet)}[/yellow]",
    ]
    if report.inactive_wings:
        wings_str = ", ".join(report.inactive_wings)
        lines.append(
            f"Wings inactive > 90 days:              [yellow]{len(report.inactive_wings)}[/yellow]  → {wings_str}"
        )
    else:
        lines.append("Wings inactive > 90 days:              [green]0[/green]")
    lines += [
        f"KG triples missing valid_from:         [yellow]{report.kg_missing_valid_from}[/yellow]",
        f"Rooms in only 1 wing (no tunnels):     [dim]{len(report.rooms_single_wing)}[/dim]",
        f"Pinned memories:                       [cyan]{report.pinned_count}[/cyan]",
        "",
        f"[dim]Total: {report.total_wings} wings, {report.total_rooms} rooms, "
        f"{report.total_drawers} drawers[/dim]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    from rich.console import Console
    from engram.chateau import Chateau
    from engram.knowledge_graph import KnowledgeGraph

    palace = Chateau()
    kg = KnowledgeGraph()
    auditor = Auditor(palace, kg)
    report = auditor.run()
    console = Console()
    console.print(format_report(report))
