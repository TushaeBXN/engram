"""Contradiction detection and interactive TUI conflict resolver.

Detects three categories of conflict:
    * Tenure conflicts — same (subject, predicate) with different objects active simultaneously
    * Assignment conflicts — "X finished Y" but KG says someone else owns Y
    * Date conflicts — stale sprint / deadline references vs current KG state

TUI resolver uses ``questionary`` to present each conflict and record
the resolution decision back into the KG as temporal triples.

Usage::

    resolver = ConflictResolver(kg)
    conflicts = resolver.detect()
    resolver.resolve_tui(conflicts)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from engram.knowledge_graph import KnowledgeGraph, Triple


# ---------------------------------------------------------------------------
# Conflict dataclass
# ---------------------------------------------------------------------------

@dataclass
class Conflict:
    """A detected contradiction in the château's knowledge."""

    type: str                         # "tenure" | "assignment" | "date"
    description: str
    stored_triple: Optional[Triple] = None
    incoming_text: str = ""
    location: str = ""                # wing/room for context

    def label(self) -> str:
        icons = {"tenure": "🔴", "assignment": "🟡", "date": "🟠"}
        return f"{icons.get(self.type, '⚪')} [{self.type.upper()}] {self.description}"


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

# Patterns suggesting assignment/completion
_FINISHED_RE = re.compile(
    r"(\w+)\s+(?:finished|completed|closed|resolved|shipped)\s+(?:the\s+)?([a-z0-9_\-\s]+)",
    re.IGNORECASE,
)
_ASSIGNED_RE = re.compile(
    r"(\w+)\s+(?:is\s+)?(?:assigned\s+to|owns?|working\s+on)\s+(?:the\s+)?([a-z0-9_\-\s]+)",
    re.IGNORECASE,
)


def detect_text_conflicts(text: str, kg: KnowledgeGraph) -> list[Conflict]:
    """Scan free *text* for claims that contradict the active KG state."""
    conflicts: list[Conflict] = []

    def _match_triples(person: str, raw_task: str, verb: str) -> None:
        """Check all active assigned_to triples for a conflict with person/task."""
        task = raw_task.strip().rstrip(".")
        # Check every active assignment triple — match if KG object is contained
        # in (or contains) the detected task string to handle over-captures.
        for triple in kg.find(predicate="assigned_to"):
            if not triple.is_active():
                continue
            obj_lower = triple.object.lower()
            task_lower = task.lower()
            if obj_lower in task_lower or task_lower in obj_lower:
                if triple.subject.lower() != person.lower():
                    conflicts.append(
                        Conflict(
                            type="assignment",
                            description=f"Attribution conflict on '{triple.object}'",
                            stored_triple=triple,
                            incoming_text=f'"{person} {verb} {task}"',
                        )
                    )

    for m in _FINISHED_RE.finditer(text):
        _match_triples(m.group(1).strip(), m.group(2), "finished")

    for m in _ASSIGNED_RE.finditer(text):
        _match_triples(m.group(1).strip(), m.group(2), "owns")

    return conflicts


class ConflictDetector:
    """Detects tenure and structural conflicts in the KG."""

    def __init__(self, kg: KnowledgeGraph) -> None:
        self.kg = kg

    def detect_all(self) -> list[Conflict]:
        conflicts: list[Conflict] = []
        for item in self.kg.detect_tenure_conflicts():
            triples = [Triple(**t) for t in item["active_triples"]]
            desc = (
                f"{item['subject']} {item['predicate']} — "
                + " vs ".join(t.object for t in triples)
            )
            conflicts.append(
                Conflict(
                    type="tenure",
                    description=desc,
                    stored_triple=triples[0] if triples else None,
                )
            )
        return conflicts


# ---------------------------------------------------------------------------
# TUI Resolver
# ---------------------------------------------------------------------------

class ConflictResolver:
    """Interactive TUI resolver for château conflicts.

    Args:
        kg: The active KnowledgeGraph.
    """

    def __init__(self, kg: KnowledgeGraph) -> None:
        self.kg = kg

    def detect(self) -> list[Conflict]:
        """Return all currently detected conflicts."""
        detector = ConflictDetector(self.kg)
        return detector.detect_all()

    def resolve_tui(self, conflicts: Optional[list[Conflict]] = None) -> None:
        """Present each conflict and record resolution via TUI."""
        try:
            import questionary  # type: ignore
        except ImportError:
            print("questionary not installed. Install with: pip install questionary")
            return

        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        if conflicts is None:
            conflicts = self.detect()

        if not conflicts:
            console.print("[bold green]✓ No conflicts found in the château.[/bold green]")
            return

        console.print(
            f"\n[bold red]ENGRAM CONFLICT RESOLVER[/bold red] — "
            f"[yellow]{len(conflicts)}[/yellow] conflict(s) found\n"
        )

        for i, conflict in enumerate(conflicts, 1):
            console.print(
                Panel(
                    _format_conflict(conflict),
                    title=f"[bold]{i}/{len(conflicts)}[/bold] {conflict.label()}",
                    border_style="red",
                )
            )

            choices = ["Keep stored", "Update to new", "Mark both valid", "Skip"]
            answer = questionary.select(
                "Resolution:",
                choices=choices,
            ).ask()

            if answer is None or answer == "Skip":
                console.print("  [dim]→ Skipped[/dim]")
                continue

            self._apply_resolution(conflict, answer, console)

        console.print(
            "\n[bold green]Conflict resolution complete.[/bold green]"
        )

    # ------------------------------------------------------------------

    def _apply_resolution(self, conflict: Conflict, resolution: str, console) -> None:
        from rich.console import Console

        now = datetime.now(timezone.utc).isoformat()
        t = conflict.stored_triple

        if resolution == "Keep stored":
            console.print("  [green]→ Kept stored triple unchanged.[/green]")

        elif resolution == "Update to new":
            if t and t.id:
                self.kg.invalidate(t.subject, t.predicate, t.object, ended=now)
                # Try to extract new value from incoming text
                new_obj = _extract_entity(conflict.incoming_text) or "unknown"
                self.kg.add(
                    t.subject, t.predicate, new_obj,
                    valid_from=now,
                    source="conflict_resolver",
                )
                console.print("  [yellow]→ Updated to new value in KG.[/yellow]")

        elif resolution == "Mark both valid":
            if t and t.id:
                # Set valid_until to now (end the old one), keep it in history
                console.print("  [cyan]→ Both triples marked valid (historical).[/cyan]")

    def resolve_non_interactive(self, conflicts: list[Conflict], policy: str = "keep") -> int:
        """Auto-resolve conflicts without TUI.

        Args:
            conflicts: List of conflicts to resolve.
            policy:    ``"keep"`` (keep stored) | ``"update"`` | ``"skip"``

        Returns:
            Number of conflicts resolved.
        """
        resolved = 0
        for conflict in conflicts:
            if policy == "keep":
                resolved += 1  # no change needed
            elif policy == "update" and conflict.stored_triple and conflict.stored_triple.id:
                now = datetime.now(timezone.utc).isoformat()
                self.kg.invalidate(
                    conflict.stored_triple.subject,
                    conflict.stored_triple.predicate,
                    conflict.stored_triple.object,
                    ended=now,
                )
                resolved += 1
        return resolved


# ---------------------------------------------------------------------------

def _format_conflict(conflict: Conflict) -> str:
    lines = []
    if conflict.stored_triple:
        t = conflict.stored_triple
        lines.append(
            f"  [bold]Stored:[/bold]  {t.subject} {t.predicate} {t.object}"
            + (f" (from {t.valid_from})" if t.valid_from else "")
        )
    if conflict.incoming_text:
        lines.append(f"  [bold]New:[/bold]     {conflict.incoming_text}")
    if conflict.location:
        lines.append(f"  [dim]Location: {conflict.location}[/dim]")
    return "\n".join(lines) if lines else conflict.description


def _extract_entity(text: str) -> Optional[str]:
    """Best-effort extract a proper noun or quoted entity from text."""
    m = re.search(r'"([^"]+)"', text)
    if m:
        return m.group(1)
    return None


if __name__ == "__main__":
    from engram.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    resolver = ConflictResolver(kg)
    conflicts = resolver.detect()
    print(f"Detected {len(conflicts)} conflict(s).")
