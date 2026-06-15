"""Typed memory system with validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MemoryType(Enum):
    """Supported memory types for structured storage."""

    INSTRUCTION = "instruction"
    FACT = "fact"
    DECISION = "decision"
    GOAL = "goal"
    COMMITMENT = "commitment"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    CONTEXT = "context"
    EVENT = "event"
    LEARNING = "learning"
    OBSERVATION = "observation"
    ARTIFACT = "artifact"
    ERROR = "error"

    @classmethod
    def from_string(cls, value: str) -> "MemoryType":
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(t.value for t in cls)
            raise ValueError(f"Invalid memory type '{value}'. Choose from: {valid}")

    @classmethod
    def all_values(cls) -> list[str]:
        return [t.value for t in cls]


@dataclass
class TypedMemory:
    """Memory entry with type, validation, and versioning."""

    content: str
    memory_type: MemoryType
    confidence: float = 0.8
    source: str = "user"  # "user" | "ai" | "miner" | "conversation"
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    previous_version_id: Optional[str] = None

    def validate(self) -> tuple[bool, str]:
        """Return (is_valid, reason).  Empty reason means valid."""
        if not self.content or len(self.content.strip()) < 3:
            return False, "Content too short (minimum 3 characters)."

        if not 0.0 <= self.confidence <= 1.0:
            return False, f"Confidence {self.confidence} out of range [0, 1]."

        validators = {
            MemoryType.INSTRUCTION: self._validate_instruction,
            MemoryType.DECISION: self._validate_decision,
            MemoryType.PREFERENCE: self._validate_preference,
        }
        fn = validators.get(self.memory_type)
        if fn and not fn():
            return False, f"Type-specific validation failed for '{self.memory_type.value}'."

        return True, ""

    def _validate_instruction(self) -> bool:
        words = {"must", "should", "always", "never", "need to", "required", "do not", "do "}
        return any(w in self.content.lower() for w in words)

    def _validate_decision(self) -> bool:
        words = {"because", "since", "due to", "based on", "therefore", "chosen", "decided"}
        return any(w in self.content.lower() for w in words)

    def _validate_preference(self) -> bool:
        words = {"prefer", "like", "dislike", "preference", "favor", "rather", "instead"}
        return any(w in self.content.lower() for w in words)

    def to_drawer_metadata(self) -> dict[str, Any]:
        """Extra metadata to attach when storing as a Drawer."""
        return {
            "mem_type": self.memory_type.value,
            "confidence": self.confidence,
            "source": self.source,
            "tags": self.tags,
            "version": self.version,
            "previous_version_id": self.previous_version_id or "",
        }


class TypedMemoryStore:
    """Add and retrieve typed memories backed by the Engram château."""

    # Map MemoryType → closest Engram hall name
    _TYPE_TO_HALL: dict[MemoryType, str] = {
        MemoryType.INSTRUCTION: "advice",
        MemoryType.FACT: "facts",
        MemoryType.DECISION: "discoveries",
        MemoryType.GOAL: "advice",
        MemoryType.COMMITMENT: "advice",
        MemoryType.PREFERENCE: "preferences",
        MemoryType.RELATIONSHIP: "facts",
        MemoryType.CONTEXT: "facts",
        MemoryType.EVENT: "events",
        MemoryType.LEARNING: "discoveries",
        MemoryType.OBSERVATION: "discoveries",
        MemoryType.ARTIFACT: "facts",
        MemoryType.ERROR: "events",
    }

    def __init__(self, palace, backend) -> None:
        self.palace = palace
        self.backend = backend

    def add(self, memory: TypedMemory, wing: str, room: Optional[str] = None) -> str:
        """Validate and store a typed memory.  Returns the new drawer ID."""
        valid, reason = memory.validate()
        if not valid:
            raise ValueError(reason)

        from engram.chateau import Drawer

        hall = self._TYPE_TO_HALL.get(memory.memory_type, "facts")
        room_name = room or memory.memory_type.value

        tags = list(memory.tags) + [f"type:{memory.memory_type.value}", f"src:{memory.source}"]
        if memory.version > 1:
            tags.append(f"v{memory.version}")

        drawer = Drawer(
            content=memory.content,
            wing=wing,
            room=room_name,
            hall=hall,
            timestamp=memory.created_at.isoformat(),
            tags=tags,
        )
        self.palace.save_drawer(drawer)

        meta = {
            "wing": wing,
            "room": room_name,
            "hall": hall,
            "timestamp": drawer.timestamp,
            "source": memory.source,
            **memory.to_drawer_metadata(),
        }
        self.backend.add(drawer.id, memory.content, meta)

        return drawer.id

    def search_by_type(
        self, query: str, memory_type: MemoryType, n: int = 10
    ) -> list[dict]:
        """Search within a specific memory type."""
        from engram.searcher import Searcher

        hall = self._TYPE_TO_HALL.get(memory_type, "facts")
        searcher = Searcher(self.backend, self.palace)
        return searcher.search(query, n=n, hall=hall)
