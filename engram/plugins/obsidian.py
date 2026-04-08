"""Obsidian vault plugin miner.

Reads ``.md`` files from an Obsidian vault directory and returns them as
Engram documents.  Supports frontmatter metadata extraction.

Usage::

    miner = ObsidianMiner()
    docs = miner.fetch("~/Documents/MyVault")

CLI::

    engram mine ~/vault --plugin obsidian --wing myproject
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engram.plugins.base import PluginMiner

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKIP_DIRS = {".obsidian", ".trash", "node_modules"}


class ObsidianMiner(PluginMiner):
    """Mines an Obsidian vault — reads all .md notes."""

    name = "obsidian"

    def fetch(self, source: str, **kwargs: Any) -> list[dict]:
        """Fetch all Markdown notes from an Obsidian vault.

        Args:
            source:       Path to the Obsidian vault root directory.
            tags_filter:  Optional list of tags to include (e.g. ["#ai", "#project"]).
            since:        Optional ISO date string — skip files older than this.

        Returns:
            List of document dicts.
        """
        vault = Path(source).expanduser()
        if not vault.exists():
            raise FileNotFoundError(f"Obsidian vault not found: {vault}")

        tags_filter: list[str] = kwargs.get("tags_filter", [])
        since_str: str = kwargs.get("since", "")
        since_dt = _parse_since(since_str)

        docs = []
        for md_path in sorted(vault.rglob("*.md")):
            # Skip hidden/system dirs
            if any(part in _SKIP_DIRS for part in md_path.parts):
                continue
            if since_dt:
                mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
                if mtime < since_dt:
                    continue

            content, frontmatter = _parse_note(md_path)
            if not content.strip():
                continue

            # Tags filter
            note_tags = frontmatter.get("tags", [])
            if isinstance(note_tags, str):
                note_tags = [note_tags]
            if tags_filter and not any(t in note_tags for t in tags_filter):
                continue

            ts = frontmatter.get("created", "") or frontmatter.get("date", "")
            if not ts:
                mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
                ts = mtime.isoformat()

            docs.append(
                {
                    "content": content,
                    "timestamp": str(ts),
                    "metadata": {
                        "source": "obsidian",
                        "path": str(md_path),
                        "title": md_path.stem,
                        "tags": note_tags,
                        **{k: str(v) for k, v in frontmatter.items() if k not in ("tags",)},
                    },
                }
            )
        return docs


# ---------------------------------------------------------------------------

def _parse_note(path: Path) -> tuple[str, dict]:
    """Return (body_text, frontmatter_dict) for a Markdown note."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", {}

    frontmatter: dict = {}
    m = _FRONTMATTER_RE.match(raw)
    if m:
        body = raw[m.end():]
        # Parse simple YAML-like frontmatter (key: value lines)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip()] = v.strip()
    else:
        body = raw

    return body.strip(), frontmatter


def _parse_since(since: str) -> datetime | None:
    if not since:
        return None
    try:
        dt = datetime.fromisoformat(since)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


if __name__ == "__main__":
    import sys
    vault = sys.argv[1] if len(sys.argv) > 1 else "~/Documents/ObsidianVault"
    miner = ObsidianMiner()
    docs = miner.fetch(vault)
    print(f"Found {len(docs)} notes in {vault}")
