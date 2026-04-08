"""Abstract PluginMiner interface — all plugin miners must implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PluginMiner(ABC):
    """Base class for source-specific miners (Obsidian, Notion, Linear…).

    Each plugin :meth:`fetch` returns a list of raw documents.  The caller
    is responsible for storing them into the château.
    """

    name: str = "base"

    @abstractmethod
    def fetch(self, source: str, **kwargs: Any) -> list[dict]:
        """Fetch documents from *source*.

        Args:
            source:   Source path or identifier (vault path, export dir…).
            **kwargs: Plugin-specific options.

        Returns:
            List of ``{"content": str, "timestamp": str, "metadata": dict}``.
        """
        ...

    def validate_source(self, source: str) -> None:
        """Raise ValueError if *source* is not usable by this plugin."""
        pass


if __name__ == "__main__":
    print("PluginMiner — abstract base.  Use get_plugin() to instantiate.")
