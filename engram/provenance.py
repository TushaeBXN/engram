"""Memory provenance and version-history tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class Provenance:
    """Records the origin and edit history of a single memory."""

    memory_id: str
    source: str  # "user" | "ai" | "miner" | "conversation" | "file"
    confidence: float = 0.8
    source_detail: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    version: int = 1
    previous_version: Optional[str] = None
    edit_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "source": self.source,
            "source_detail": self.source_detail,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "confidence": self.confidence,
            "version": self.version,
            "previous_version": self.previous_version,
            "edit_reason": self.edit_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Provenance":
        return cls(
            memory_id=d["memory_id"],
            source=d["source"],
            source_detail=d.get("source_detail"),
            created_at=datetime.fromisoformat(d["created_at"]),
            created_by=d.get("created_by"),
            confidence=d.get("confidence", 0.8),
            version=d.get("version", 1),
            previous_version=d.get("previous_version"),
            edit_reason=d.get("edit_reason"),
        )


class ProvenanceTracker:
    """Persist and traverse provenance records on the filesystem."""

    def __init__(self, chateau_path: Path) -> None:
        self.prov_dir = chateau_path / "provenance"
        self.prov_dir.mkdir(parents=True, exist_ok=True)

    def track(self, provenance: Provenance) -> None:
        """Write a provenance record to disk."""
        prov_file = self.prov_dir / f"{provenance.memory_id}.json"
        prov_file.write_text(json.dumps(provenance.to_dict(), indent=2))

    def get(self, memory_id: str) -> Optional[Provenance]:
        """Fetch the provenance record for a single memory ID."""
        prov_file = self.prov_dir / f"{memory_id}.json"
        if not prov_file.exists():
            return None
        return Provenance.from_dict(json.loads(prov_file.read_text()))

    def get_history(self, memory_id: str) -> list[Provenance]:
        """Walk the version chain and return oldest-first history."""
        history: list[Provenance] = []
        current_id: Optional[str] = memory_id

        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            prov = self.get(current_id)
            if prov is None:
                break
            history.append(prov)
            current_id = prov.previous_version

        history.reverse()
        return history

    def source_summary(self) -> dict[str, int]:
        """Count provenance records by source across the whole château."""
        counts: dict[str, int] = {}
        for prov_file in self.prov_dir.glob("*.json"):
            try:
                data = json.loads(prov_file.read_text())
                src = data.get("source", "unknown")
                counts[src] = counts.get(src, 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue
        return counts
