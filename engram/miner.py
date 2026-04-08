"""Project file ingest — mines code, docs, and notes into the château.

Supported file types:
    * Python / JS / TS / Go / Rust — code files (code-aware ES compression)
    * Markdown / RST / txt — prose notes
    * JSON / YAML — config / structured data
    * Any other text file — plain ingest

Usage::

    miner = Miner(palace, backend)
    results = miner.mine("/path/to/project", wing="myapp", since="2026-01-01")
"""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engram.palace import Palace, Drawer, HALL_TYPES
from engram.shorthand import compress
from engram.config import load_config


# File extensions → hall type
_EXT_HALL: dict[str, str] = {
    ".py": "discoveries",
    ".js": "discoveries",
    ".ts": "discoveries",
    ".tsx": "discoveries",
    ".jsx": "discoveries",
    ".go": "discoveries",
    ".rs": "discoveries",
    ".c": "discoveries",
    ".cpp": "discoveries",
    ".java": "discoveries",
    ".rb": "discoveries",
    ".php": "discoveries",
    ".md": "facts",
    ".rst": "facts",
    ".txt": "facts",
    ".json": "facts",
    ".yaml": "facts",
    ".yml": "facts",
    ".toml": "facts",
    ".env": "facts",
    ".sh": "advice",
    ".bash": "advice",
    ".zsh": "advice",
}

_CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".cpp", ".java", ".rb", ".php"}

# Files/directories to skip
_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    "chroma_db", ".engram",
}
_SKIP_FILES = {".DS_Store", "Thumbs.db", ".gitignore"}
_MAX_FILE_BYTES = 500_000  # skip files > 500 KB


def _is_text_file(path: Path) -> bool:
    mt, _ = mimetypes.guess_type(str(path))
    if mt and not mt.startswith("text"):
        return False
    try:
        path.read_bytes()[:512].decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def _file_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


class Miner:
    """Ingests project files into the château.

    Args:
        palace:   The Palace to write drawers into.
        backend:  The active VectorBackend for embedding.
        config:   Merged config dict (uses load_config() if None).
    """

    def __init__(self, palace: Palace, backend, config: Optional[dict] = None) -> None:
        self.palace = palace
        self.backend = backend
        self.config = config or load_config()

    # ------------------------------------------------------------------

    def mine(
        self,
        path: str | Path,
        wing: str = "default",
        room: Optional[str] = None,
        mode: str = "files",       # "files" | "convos" (delegated to ConvoMiner)
        since: Optional[str] = None,
        plugin: Optional[str] = None,
    ) -> list[Drawer]:
        """Mine *path* recursively and return all created drawers."""
        from engram.convo_miner import ConvoMiner  # local import avoids circular

        src = Path(path).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"Path not found: {src}")

        if mode == "convos":
            cm = ConvoMiner(self.palace, self.backend, self.config)
            return cm.mine(src, wing=wing, room=room, since=since)

        since_dt = _parse_since(since)
        drawers: list[Drawer] = []

        if src.is_file():
            d = self._mine_file(src, wing, room or src.stem, since_dt)
            if d:
                drawers.append(d)
        else:
            for fpath in sorted(src.rglob("*")):
                if not fpath.is_file():
                    continue
                if any(part in _SKIP_DIRS for part in fpath.parts):
                    continue
                if fpath.name in _SKIP_FILES:
                    continue
                d = self._mine_file(fpath, wing, room or fpath.parent.name, since_dt)
                if d:
                    drawers.append(d)

        return drawers

    def _mine_file(
        self,
        path: Path,
        wing: str,
        room: str,
        since: Optional[datetime],
    ) -> Optional[Drawer]:
        """Ingest a single file.  Returns None if skipped."""
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        if since:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < since:
                return None
        if not _is_text_file(path):
            return None

        ext = path.suffix.lower()
        hall = _EXT_HALL.get(ext, "facts")
        is_code = ext in _CODE_EXTS

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        if not content.strip():
            return None

        compressed = compress(content, is_code=is_code)

        drawer = Drawer(
            content=compressed,
            wing=wing,
            room=room,
            hall=hall,
            tags=[ext.lstrip("."), "file"],
        )
        self.palace.save_drawer(drawer)
        self.backend.add(
            id=drawer.id,
            text=content[:2000],  # embed uncompressed for better retrieval
            metadata={
                "wing": wing,
                "room": room,
                "hall": hall,
                "path": str(path),
                "timestamp": drawer.timestamp,
            },
        )
        return drawer


# ---------------------------------------------------------------------------

def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        dt = datetime.fromisoformat(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


if __name__ == "__main__":
    from engram.palace import Palace
    from engram.backends import get_backend
    from engram.config import load_config

    cfg = load_config()
    palace = Palace()
    backend = get_backend(cfg["vector_backend"])
    miner = Miner(palace, backend, cfg)
    print("Miner ready.  Usage: miner.mine('/path/to/project', wing='myapp')")
