"""Linear plugin miner — reads a Linear issue export or live API.

Export mode reads a ``issues.json`` (Linear CSV/JSON export).
API mode requires ``LINEAR_API_KEY`` env var.

Usage::

    miner = LinearMiner()
    docs = miner.fetch("~/Downloads/linear-export")

# TODO: implement full GraphQL pagination for live API
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engram.plugins.base import PluginMiner


class LinearMiner(PluginMiner):
    """Mines a Linear issues export or the Linear GraphQL API (stub)."""

    name = "linear"

    def fetch(self, source: str, **kwargs: Any) -> list[dict]:
        """Fetch Linear issues from *source*.

        Args:
            source: Path to a Linear JSON/CSV export directory or file.
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
        src = Path(source).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"Linear export not found: {src}")

        json_files = list(src.rglob("*.json")) if src.is_dir() else [src]
        docs = []
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            issues = data if isinstance(data, list) else data.get("issues", [])
            for issue in issues:
                content = _issue_to_text(issue)
                if not content:
                    continue
                ts = issue.get("createdAt") or issue.get("updatedAt") or ""
                docs.append(
                    {
                        "content": content,
                        "timestamp": ts,
                        "metadata": {
                            "source": "linear",
                            "id": issue.get("id", ""),
                            "title": issue.get("title", ""),
                            "status": issue.get("state", {}).get("name", "") if isinstance(issue.get("state"), dict) else str(issue.get("state", "")),
                            "assignee": issue.get("assignee", {}).get("name", "") if isinstance(issue.get("assignee"), dict) else "",
                        },
                    }
                )
        return docs

    def _fetch_api(self, **kwargs: Any) -> list[dict]:
        """# TODO: implement Linear GraphQL API pagination."""
        api_key = os.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            raise EnvironmentError("LINEAR_API_KEY environment variable not set.")
        raise NotImplementedError(
            "Live Linear API mining is not yet implemented.  "
            "Export your issues as JSON and use mode='export'."
        )


# ---------------------------------------------------------------------------

def _issue_to_text(issue: dict) -> str:
    """Convert a Linear issue dict to a readable string."""
    parts = []
    if issue.get("title"):
        parts.append(f"Title: {issue['title']}")
    if issue.get("description"):
        parts.append(f"Description: {issue['description'][:500]}")
    state = issue.get("state")
    if isinstance(state, dict):
        parts.append(f"Status: {state.get('name', '')}")
    elif state:
        parts.append(f"Status: {state}")
    assignee = issue.get("assignee")
    if isinstance(assignee, dict) and assignee.get("name"):
        parts.append(f"Assignee: {assignee['name']}")
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "~/Downloads/linear-export"
    miner = LinearMiner()
    docs = miner.fetch(src)
    print(f"Found {len(docs)} Linear issues in {src}")
