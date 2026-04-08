"""Specialist agent diary system.

Each agent has a persistent identity file at::

    ~/.engram/agents/{name}.json

and a diary of ES-compressed entries.  Agents load their own history at
runtime, so they can pick up mid-task without relying on session memory.

Diary entries are written in Engram Shorthand for compact context loading.

Usage::

    diary = AgentDiary("code-reviewer")
    diary.write("Reviewed auth.py — flagged missing rate-limit middleware")
    for entry in diary.read(last_n=5):
        print(entry)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engram.config import ENGRAM_DIR
from engram.shorthand import compress, decompress

AGENTS_DIR = ENGRAM_DIR / "agents"


@dataclass
class AgentProfile:
    """Persistent identity for a specialist agent."""

    name: str
    focus: str = ""           # e.g. "security review", "documentation"
    model_hint: str = ""      # e.g. "claude-opus-4-6"
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    diary_path: str = ""      # relative to AGENTS_DIR

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DiaryEntry:
    """A single ES-compressed diary entry."""

    agent: str
    content: str              # ES-compressed text
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DiaryEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def readable(self) -> str:
        return decompress(self.content)


class AgentDiary:
    """Read/write diary for a named agent.

    Args:
        agent_name: Unique agent identifier (used as filename).
    """

    def __init__(self, agent_name: str) -> None:
        self.name = agent_name
        AGENTS_DIR.expanduser().mkdir(parents=True, exist_ok=True)
        self._profile_path = (AGENTS_DIR / f"{agent_name}.json").expanduser()
        self._diary_path = (AGENTS_DIR / f"{agent_name}_diary.jsonl").expanduser()
        self._profile: Optional[AgentProfile] = None

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def load_profile(self) -> AgentProfile:
        if self._profile:
            return self._profile
        if self._profile_path.exists():
            try:
                d = json.loads(self._profile_path.read_text())
                self._profile = AgentProfile.from_dict(d)
                return self._profile
            except Exception:
                pass
        self._profile = AgentProfile(name=self.name)
        return self._profile

    def save_profile(self, profile: AgentProfile) -> None:
        self._profile = profile
        self._profile_path.write_text(json.dumps(profile.to_dict(), indent=2))

    def create(self, focus: str = "", model_hint: str = "") -> AgentProfile:
        """Create or update the agent profile."""
        profile = AgentProfile(
            name=self.name,
            focus=focus,
            model_hint=model_hint,
            diary_path=str(self._diary_path.relative_to(AGENTS_DIR.expanduser())),
        )
        self.save_profile(profile)
        return profile

    # ------------------------------------------------------------------
    # Diary
    # ------------------------------------------------------------------

    def write(self, text: str, tags: Optional[list[str]] = None) -> DiaryEntry:
        """Write a new diary entry (ES-compressed)."""
        entry = DiaryEntry(
            agent=self.name,
            content=compress(text),
            tags=tags or [],
        )
        with self._diary_path.open("a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
        return entry

    def read(self, last_n: int = 10) -> list[DiaryEntry]:
        """Return the most recent *last_n* diary entries."""
        if not self._diary_path.exists():
            return []
        lines = self._diary_path.read_text().strip().splitlines()
        entries = []
        for line in lines:
            try:
                entries.append(DiaryEntry.from_dict(json.loads(line)))
            except Exception:
                continue
        return entries[-last_n:]

    def context_block(self, last_n: int = 5) -> str:
        """Return ES context block for injection into agent prompts."""
        profile = self.load_profile()
        entries = self.read(last_n=last_n)
        lines = [f"[agent:{self.name}|focus:{profile.focus}]"]
        for e in entries:
            ts = e.timestamp[:16]
            lines.append(f"  [{ts}] {e.content}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Wipe the diary (irreversible)."""
        if self._diary_path.exists():
            self._diary_path.unlink()


# ---------------------------------------------------------------------------
# Convenience functions (for MCP tool wrappers)
# ---------------------------------------------------------------------------

def engram_diary_write(agent: str, entry: str, tags: Optional[list[str]] = None) -> dict:
    """Write a diary entry.  Returns the serialised entry."""
    diary = AgentDiary(agent)
    e = diary.write(entry, tags=tags)
    return e.to_dict()


def engram_diary_read(agent: str, last_n: int = 10) -> list[dict]:
    """Return the last *last_n* diary entries as dicts."""
    diary = AgentDiary(agent)
    return [e.to_dict() for e in diary.read(last_n=last_n)]


def list_agents() -> list[dict]:
    """Return all known agent profiles."""
    agents_dir = AGENTS_DIR.expanduser()
    if not agents_dir.exists():
        return []
    profiles = []
    for p in sorted(agents_dir.glob("*.json")):
        if p.name.endswith("_diary.jsonl"):
            continue
        try:
            profiles.append(json.loads(p.read_text()))
        except Exception:
            continue
    return profiles


if __name__ == "__main__":
    diary = AgentDiary("demo-agent")
    diary.create(focus="testing engram", model_hint="claude-sonnet-4-6")
    diary.write("Tested ES compression — 6x average ratio achieved")
    for entry in diary.read():
        print(f"[{entry.timestamp[:16]}]", entry.readable())
