"""Engram memory château — Wing / Room / Hall / Closet / Drawer data model.

The château organises everything the AI has learned into a navigable
hierarchy:

    Wing  (person or project)
      └── Room  (named topic, e.g. "auth-migration")
            ├── Hall  (memory type: facts | events | discoveries |
            │           preferences | advice)
            │     ├── Closet  (ES-compressed summary — fast AI read)
            │     └── Drawer  (verbatim original — never summarised)
            └── Tunnel  (cross-wing link when a room spans wings)

All data lives under ~/.engram/chateau/ as nested directories + JSON
files. Nothing is stored in a database — the filesystem IS the model.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engram.config import get_chateau_path
from engram.fsio import atomic_write_text

# ---------------------------------------------------------------------------
# Hall types recognised by the château
# ---------------------------------------------------------------------------
HALL_TYPES = ("facts", "events", "discoveries", "preferences", "advice")
# Directories at the château root that hold bookkeeping, not wings.
RESERVED_DIRS = ("provenance",)


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

class InvalidNameError(ValueError):
    """Raised when a wing / room / hall / drawer / agent name is unsafe as a path part."""


def validate_name(name: str, kind: str = "name") -> str:
    """Return *name* if it is safe to use as a single path component.

    Names arrive from the CLI, miners and MCP clients, and become directory or
    file names, so anything that could step outside the château is rejected.
    """
    if not isinstance(name, str) or not name.strip():
        raise InvalidNameError(f"{kind} must be a non-empty string")
    if name in (".", "..") or Path(name).anchor or any(c in name for c in ("/", "\\", "\0")):
        raise InvalidNameError(f"Invalid {kind} {name!r}: must not contain '/', '\\' or be '.' / '..'")
    return name


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Drawer:
    """Verbatim memory unit.  Never summarised — source of truth.

    ``compressed`` is False for drawers that hold the original text. Drawers
    written before Engram stored originals hold ES-compressed text; they have
    no ``compressed`` key on disk and load with ``compressed=True``.
    """

    content: str
    wing: str
    room: str
    hall: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pinned: bool = False
    decay_weight: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tags: list[str] = field(default_factory=list)
    compressed: bool = False
    # Where it came from: user, primary, secondary, tool or inference (see relations.py).
    source: str = ""
    source_ref: str = ""   # citation, URL or document the memory was taken from

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("source", "source_ref"):  # unset: keep the file as older versions wrote it
            if not d[key]:
                del d[key]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Drawer:
        d = {"compressed": True, **d}  # legacy drawers stored ES-compressed text
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})  # ignore fields from newer versions

    def text(self) -> str:
        """Readable content: the original text, or an expansion of legacy ES text."""
        if self.compressed:
            from engram.shorthand import decompress
            return decompress(self.content)
        return self.content

    def age_days(self) -> float:
        """Days since this drawer was created."""
        ts = datetime.fromisoformat(self.timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 86400


@dataclass
class Closet:
    """ES-compressed summary of a hall — loaded quickly into AI context."""

    content: str          # Engram Shorthand compressed text
    wing: str
    room: str
    hall: str
    updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Closet:
        return cls(**d)


@dataclass
class Hall:
    """A typed partition of a room (facts, events, discoveries…)."""

    name: str       # one of HALL_TYPES
    wing: str
    room: str

    def validate(self) -> None:
        if self.name not in HALL_TYPES:
            raise ValueError(f"Unknown hall type '{self.name}'. Choose from {HALL_TYPES}")


@dataclass
class Tunnel:
    """Cross-wing link — marks that a room appears in multiple wings."""

    room: str
    source_wing: str
    target_wing: str
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Tunnel:
        return cls(**d)


@dataclass
class Room:
    """A named topic within a wing (e.g. 'auth-migration')."""

    name: str
    wing: str
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Room:
        return cls(**d)


@dataclass
class Wing:
    """Top-level organisational unit — a person or project."""

    name: str
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Wing:
        return cls(**d)


# ---------------------------------------------------------------------------
# Palace — the château itself
# ---------------------------------------------------------------------------

class Chateau:
    """Manages the full château: reads/writes Wings, Rooms, Drawers, and
    Closets to/from the filesystem under chateau_path.

    Directory layout::

        chateau_path/
          {wing}/
            wing.json
            {room}/
              room.json
              {hall}/
                closet.es          ← ES-compressed closet text
                {uuid}.json        ← individual Drawer files
            tunnels.json           ← cross-wing tunnel records
    """

    def __init__(self, chateau_path: Optional[Path] = None, redact: Optional[bool] = None) -> None:
        self.path: Path = (chateau_path or get_chateau_path()).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
        # Secret redaction before saving (engram.redact). None: follow the
        # "redact_secrets" config key for the default château, off otherwise.
        if redact is None and chateau_path is None:
            from engram.config import load_config
            redact = bool(load_config().get("redact_secrets", False))
        self.redact = bool(redact)

    # ------------------------------------------------------------------
    # Wing operations
    # ------------------------------------------------------------------

    def wing_path(self, wing: str) -> Path:
        return self.path / validate_name(wing, "wing")

    def list_wings(self) -> list[Wing]:
        wings = []
        for p in sorted(self.path.iterdir()):
            if p.is_dir() and p.name not in RESERVED_DIRS:
                meta = p / "wing.json"
                if meta.exists():
                    wings.append(Wing.from_dict(json.loads(meta.read_text())))
                else:
                    wings.append(Wing(name=p.name))
        return wings

    def get_wing(self, name: str) -> Optional[Wing]:
        p = self.wing_path(name) / "wing.json"
        if p.exists():
            return Wing.from_dict(json.loads(p.read_text()))
        if self.wing_path(name).exists():
            return Wing(name=name)
        return None

    def create_wing(self, name: str, description: str = "") -> Wing:
        wp = self.wing_path(name)
        wp.mkdir(parents=True, exist_ok=True)
        wing = Wing(name=name, description=description)
        atomic_write_text(wp / "wing.json", json.dumps(wing.to_dict(), indent=2))
        return wing

    def ensure_wing(self, name: str) -> Wing:
        return self.get_wing(name) or self.create_wing(name)

    # ------------------------------------------------------------------
    # Room operations
    # ------------------------------------------------------------------

    def room_path(self, wing: str, room: str) -> Path:
        return self.wing_path(wing) / validate_name(room, "room")

    def list_rooms(self, wing: str) -> list[Room]:
        wp = self.wing_path(wing)
        if not wp.exists():
            return []
        rooms = []
        for p in sorted(wp.iterdir()):
            if p.is_dir():
                meta = p / "room.json"
                if meta.exists():
                    rooms.append(Room.from_dict(json.loads(meta.read_text())))
                else:
                    rooms.append(Room(name=p.name, wing=wing))
        return rooms

    def get_room(self, wing: str, room: str) -> Optional[Room]:
        p = self.room_path(wing, room) / "room.json"
        if p.exists():
            return Room.from_dict(json.loads(p.read_text()))
        if self.room_path(wing, room).exists():
            return Room(name=room, wing=wing)
        return None

    def create_room(self, wing: str, name: str, description: str = "") -> Room:
        self.ensure_wing(wing)
        rp = self.room_path(wing, name)
        rp.mkdir(parents=True, exist_ok=True)
        # Create hall directories
        for hall in HALL_TYPES:
            (rp / hall).mkdir(exist_ok=True)
        room = Room(name=name, wing=wing, description=description)
        atomic_write_text(rp / "room.json", json.dumps(room.to_dict(), indent=2))
        return room

    def ensure_room(self, wing: str, name: str) -> Room:
        return self.get_room(wing, name) or self.create_room(wing, name)

    # ------------------------------------------------------------------
    # Drawer operations
    # ------------------------------------------------------------------

    def hall_path(self, wing: str, room: str, hall: str) -> Path:
        return self.room_path(wing, room) / validate_name(hall, "hall")

    def _drawer_file(self, wing: str, room: str, hall: str, drawer_id: str) -> Path:
        return self.hall_path(wing, room, hall) / f"{validate_name(drawer_id, 'drawer id')}.json"

    def save_drawer(self, drawer: Drawer) -> Path:
        """Persist a drawer to disk.  Creates wing/room/hall if needed.

        With redaction on, secrets in ``drawer.content`` are replaced first
        (in place, so whatever indexes the drawer next sees the same text).
        """
        if self.redact:
            from engram.redact import redact_secrets
            drawer.content = redact_secrets(drawer.content)
        self.ensure_room(drawer.wing, drawer.room)
        dest = self._drawer_file(drawer.wing, drawer.room, drawer.hall, drawer.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, json.dumps(drawer.to_dict(), indent=2))
        return dest

    def get_drawer(self, wing: str, room: str, hall: str, drawer_id: str) -> Optional[Drawer]:
        p = self._drawer_file(wing, room, hall, drawer_id)
        if p.exists():
            return Drawer.from_dict(json.loads(p.read_text()))
        return None

    def iter_drawers(
        self,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        hall: Optional[str] = None,
    ) -> Iterator[Drawer]:
        """Yield all drawers, optionally filtered by wing / room / hall."""
        for wdir in sorted(self.path.iterdir()):
            if not wdir.is_dir() or (wing and wdir.name != wing):
                continue
            for rdir in sorted(wdir.iterdir()):
                if not rdir.is_dir() or rdir.name == "wing.json":
                    continue
                if room and rdir.name != room:
                    continue
                for hdir in sorted(rdir.iterdir()):
                    if not hdir.is_dir():
                        continue
                    if hall and hdir.name != hall:
                        continue
                    for jf in sorted(hdir.glob("*.json")):
                        try:
                            yield Drawer.from_dict(json.loads(jf.read_text()))
                        except (json.JSONDecodeError, TypeError, KeyError):
                            continue

    def unreadable_files(self) -> list[Path]:
        """Drawer files that can't be read back, and leftovers of an interrupted write.

        Reading skips a damaged file instead of failing, so without this a
        damaged memory would just silently vanish from search and listings.
        """
        bad = []
        for jf in sorted(self.path.glob("*/*/*/*.json")):
            if jf.parts[-4] in RESERVED_DIRS:
                continue
            try:
                Drawer.from_dict(json.loads(jf.read_text()))
            except (OSError, ValueError, TypeError, KeyError):
                bad.append(jf)
        bad.extend(sorted(self.path.glob("**/.*.tmp")))
        return bad

    def delete_drawer(self, wing: str, room: str, hall: str, drawer_id: str) -> bool:
        p = self._drawer_file(wing, room, hall, drawer_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def delete_drawer_by_id(self, drawer_id: str) -> int:
        """Delete every stored copy of *drawer_id*, in any wing/room/hall."""
        name = f"{validate_name(drawer_id, 'drawer id')}.json"
        removed = 0
        for p in self.path.glob(f"*/*/*/{name}"):
            p.unlink()
            removed += 1
        return removed

    def find_drawer(self, id_or_prefix: str) -> Optional[Drawer]:
        """The drawer with this ID, or the only one whose ID starts with it.

        Accepts a prefix of at least 4 characters (``engram search`` shows a short one),
        and raises ``LookupError`` when a prefix matches more than one drawer.
        """
        key = (id_or_prefix or "").strip()
        if len(key) < 4 or any(c in key for c in "/\\*?[]\0"):
            return None
        exact = list(self.path.glob(f"*/*/*/{key}.json"))
        matches = exact or list(self.path.glob(f"*/*/*/{key}*.json"))
        ids = {p.stem for p in matches}
        if len(ids) > 1:
            raise LookupError(f"'{key}' matches {len(ids)} memories; use more of the ID")
        for p in matches:
            try:
                return Drawer.from_dict(json.loads(p.read_text()))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return None

    def pin_drawer(self, drawer_id: str) -> Optional[Drawer]:
        """Find a drawer by ID anywhere in the château and pin it."""
        for drawer in self.iter_drawers():
            if drawer.id == drawer_id:
                drawer.pinned = True
                self.save_drawer(drawer)
                return drawer
        return None

    # ------------------------------------------------------------------
    # Closet operations
    # ------------------------------------------------------------------

    def closet_path(self, wing: str, room: str, hall: str) -> Path:
        return self.hall_path(wing, room, hall) / "closet.es"

    def save_closet(self, closet: Closet) -> None:
        self.ensure_room(closet.wing, closet.room)
        hp = self.hall_path(closet.wing, closet.room, closet.hall)
        hp.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.closet_path(closet.wing, closet.room, closet.hall), closet.content)

    def get_closet(self, wing: str, room: str, hall: str) -> Optional[Closet]:
        p = self.closet_path(wing, room, hall)
        if p.exists():
            return Closet(
                content=p.read_text(),
                wing=wing,
                room=room,
                hall=hall,
                updated=datetime.fromtimestamp(
                    p.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            )
        return None

    # ------------------------------------------------------------------
    # Tunnel operations
    # ------------------------------------------------------------------

    def _tunnels_path(self, wing: str) -> Path:
        return self.wing_path(wing) / "tunnels.json"

    def list_tunnels(self, wing: str) -> list[Tunnel]:
        p = self._tunnels_path(wing)
        if not p.exists():
            return []
        try:
            return [Tunnel.from_dict(d) for d in json.loads(p.read_text())]
        except (json.JSONDecodeError, TypeError):
            return []

    def add_tunnel(self, room: str, source_wing: str, target_wing: str) -> Tunnel:
        tunnels = self.list_tunnels(source_wing)
        t = Tunnel(room=room, source_wing=source_wing, target_wing=target_wing)
        tunnels.append(t)
        self.ensure_wing(source_wing)
        atomic_write_text(self._tunnels_path(source_wing), json.dumps([x.to_dict() for x in tunnels], indent=2))
        return t

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        wings = self.list_wings()
        total_drawers = 0
        total_rooms = 0
        total_closets = 0
        for w in wings:
            rooms = self.list_rooms(w.name)
            total_rooms += len(rooms)
            for r in rooms:
                for h in HALL_TYPES:
                    total_drawers += sum(
                        1 for _ in (self.hall_path(w.name, r.name, h)).glob("*.json")
                        if (self.hall_path(w.name, r.name, h)).exists()
                    )
                    if self.closet_path(w.name, r.name, h).exists():
                        total_closets += 1
        return {
            "wings": len(wings),
            "rooms": total_rooms,
            "drawers": total_drawers,
            "closets": total_closets,
        }


if __name__ == "__main__":
    chateau = Chateau()
    stats = chateau.stats()
    print("Château stats:", stats)
