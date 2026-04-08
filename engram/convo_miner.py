"""Conversation export ingest — mines Claude, ChatGPT, and Slack exports.

Supports:
    * Claude export JSON (``conversations.json``)
    * ChatGPT export JSON (``conversations.json``)
    * Plain Markdown conversation transcripts
    * Slack channel export (``messages.json``)

Usage::

    cm = ConvoMiner(palace, backend)
    cm.mine("/path/to/exports", wing="work", room="design-decisions")
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engram.palace import Palace, Drawer
from engram.shorthand import compress
from engram.config import load_config


# ---------------------------------------------------------------------------
# Format detectors
# ---------------------------------------------------------------------------

def _detect_format(path: Path) -> str:
    """Return one of: 'claude', 'chatgpt', 'slack', 'markdown', 'unknown'."""
    if path.suffix == ".md":
        return "markdown"
    if path.suffix != ".json":
        return "unknown"
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return "unknown"

    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        if "chat_messages" in first:
            return "claude"
        if "mapping" in first:
            return "chatgpt"
        if "text" in first and "ts" in first:
            return "slack"
    return "unknown"


# ---------------------------------------------------------------------------
# Format parsers → list of {"role": str, "text": str, "timestamp": str}
# ---------------------------------------------------------------------------

def _parse_claude(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    messages = []
    for convo in (data if isinstance(data, list) else [data]):
        for msg in convo.get("chat_messages", []):
            role = msg.get("sender", "unknown")
            parts = msg.get("content", [])
            text = ""
            if isinstance(parts, list):
                text = "\n".join(
                    p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")
                )
            elif isinstance(parts, str):
                text = parts
            ts = msg.get("created_at", "")
            if text.strip():
                messages.append({"role": role, "text": text.strip(), "timestamp": ts})
    return messages


def _parse_chatgpt(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    messages = []
    for convo in (data if isinstance(data, list) else [data]):
        mapping = convo.get("mapping", {})
        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "unknown")
            parts = msg.get("content", {}).get("parts", [])
            text = "\n".join(str(p) for p in parts if p)
            ts = str(msg.get("create_time", ""))
            if text.strip():
                messages.append({"role": role, "text": text.strip(), "timestamp": ts})
    return messages


def _parse_slack(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    messages = []
    for msg in (data if isinstance(data, list) else []):
        text = msg.get("text", "").strip()
        ts_raw = msg.get("ts", "")
        user = msg.get("user", msg.get("username", "unknown"))
        if text:
            ts = ""
            try:
                ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).isoformat()
            except (ValueError, TypeError):
                pass
            messages.append({"role": user, "text": text, "timestamp": ts})
    return messages


def _parse_markdown(path: Path) -> list[dict]:
    """Parse a Markdown transcript with ``**Human:**`` / ``**Assistant:**`` headers."""
    text = path.read_text(encoding="utf-8", errors="replace")
    messages = []
    # Split on speaker headers
    parts = re.split(r"\*\*(Human|Assistant|User|Claude):\*\*", text, flags=re.IGNORECASE)
    role = "unknown"
    for part in parts:
        part = part.strip()
        if part.lower() in ("human", "user"):
            role = "human"
        elif part.lower() in ("assistant", "claude"):
            role = "assistant"
        elif part:
            messages.append({"role": role, "text": part, "timestamp": ""})
    return messages


_PARSERS = {
    "claude": _parse_claude,
    "chatgpt": _parse_chatgpt,
    "slack": _parse_slack,
    "markdown": _parse_markdown,
}


# ---------------------------------------------------------------------------
# ConvoMiner
# ---------------------------------------------------------------------------

_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}


class ConvoMiner:
    """Ingests conversation exports into the château.

    Args:
        palace:   The Palace to write drawers into.
        backend:  The active VectorBackend.
        config:   Merged config dict.
    """

    def __init__(self, palace: Palace, backend, config: Optional[dict] = None) -> None:
        self.palace = palace
        self.backend = backend
        self.config = config or load_config()

    # ------------------------------------------------------------------

    def mine(
        self,
        path: Path,
        wing: str = "default",
        room: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[Drawer]:
        """Mine all conversation exports under *path*."""
        since_dt = _parse_since(since)
        drawers: list[Drawer] = []

        files = [path] if path.is_file() else sorted(path.rglob("*"))
        for fpath in files:
            if not fpath.is_file():
                continue
            if any(part in _SKIP_DIRS for part in fpath.parts):
                continue
            if since_dt:
                mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
                if mtime < since_dt:
                    continue
            fmt = _detect_format(fpath)
            if fmt == "unknown":
                continue
            try:
                messages = _PARSERS[fmt](fpath)
            except Exception:
                continue
            room_name = room or fpath.stem
            for msg in messages:
                d = self._store_message(msg, wing, room_name)
                if d:
                    drawers.append(d)
        return drawers

    def _store_message(self, msg: dict, wing: str, room: str) -> Optional[Drawer]:
        text = msg["text"]
        if len(text) < 20:
            return None
        hall = "facts" if msg["role"] in ("human", "user") else "discoveries"
        compressed = compress(text)
        drawer = Drawer(
            content=compressed,
            wing=wing,
            room=room,
            hall=hall,
            timestamp=msg["timestamp"] or datetime.now(timezone.utc).isoformat(),
            tags=["conversation", msg["role"]],
        )
        self.palace.save_drawer(drawer)
        self.backend.add(
            id=drawer.id,
            text=text[:2000],
            metadata={
                "wing": wing,
                "room": room,
                "hall": hall,
                "role": msg["role"],
                "timestamp": drawer.timestamp,
            },
        )
        return drawer


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        dt = datetime.fromisoformat(since)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


if __name__ == "__main__":
    from engram.palace import Palace
    from engram.backends import get_backend
    cfg = load_config()
    palace = Palace()
    backend = get_backend(cfg["vector_backend"])
    cm = ConvoMiner(palace, backend, cfg)
    print("ConvoMiner ready.  Usage: cm.mine('/path/to/exports', wing='myapp')")
