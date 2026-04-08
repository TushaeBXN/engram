"""Notion plugin miner — reads a Notion export directory.

Notion exports as HTML or Markdown ZIP archives.  Unzip first, then::

    miner = NotionMiner()
    docs = miner.fetch("~/Downloads/notion-export")

For live API access set ``NOTION_TOKEN`` in your environment and pass
``mode="api"``.  The API path is a stub — contributions welcome.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engram.plugins.base import PluginMiner


class NotionMiner(PluginMiner):
    """Mines a Notion export (Markdown files) or live API (stub)."""

    name = "notion"

    def fetch(self, source: str, **kwargs: Any) -> list[dict]:
        """Fetch Notion pages from *source*.

        Args:
            source: Path to a Notion Markdown export directory.
            mode:   ``"export"`` (default) | ``"api"`` (stub).

        Returns:
            List of document dicts.
        """
        mode = kwargs.get("mode", "export")
        if mode == "api":
            return self._fetch_api(**kwargs)
        return self._fetch_export(source, **kwargs)

    # ------------------------------------------------------------------

    def _fetch_export(self, source: str, **kwargs: Any) -> list[dict]:
        """Read all .md files from a Notion Markdown export directory."""
        export_dir = Path(source).expanduser()
        if not export_dir.exists():
            raise FileNotFoundError(f"Notion export directory not found: {export_dir}")

        docs = []
        for md_path in sorted(export_dir.rglob("*.md")):
            try:
                content = md_path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not content:
                continue
            mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
            docs.append(
                {
                    "content": content,
                    "timestamp": mtime.isoformat(),
                    "metadata": {
                        "source": "notion",
                        "path": str(md_path),
                        "title": md_path.stem,
                    },
                }
            )
        return docs

    def _fetch_api(self, **kwargs: Any) -> list[dict]:
        """Fetch pages via the Notion API.  Requires NOTION_TOKEN env var.

        # TODO: implement full Notion API pagination
        """
        token = os.environ.get("NOTION_TOKEN", "")
        if not token:
            raise EnvironmentError(
                "NOTION_TOKEN environment variable not set. "
                "Export your Notion workspace to Markdown instead."
            )
        # Stub — real implementation requires notion-client library
        raise NotImplementedError(
            "Live Notion API mining is not yet implemented.  "
            "Export your workspace to Markdown and use mode='export'."
        )


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "~/Downloads/notion-export"
    miner = NotionMiner()
    docs = miner.fetch(src)
    print(f"Found {len(docs)} Notion pages in {src}")
