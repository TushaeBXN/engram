"""Engram plugin miner registry."""

from __future__ import annotations

from engram.plugins.base import PluginMiner


def get_plugin(name: str) -> PluginMiner:
    """Return an initialised PluginMiner by name."""
    if name == "obsidian":
        from engram.plugins.obsidian import ObsidianMiner
        return ObsidianMiner()
    if name == "notion":
        from engram.plugins.notion import NotionMiner
        return NotionMiner()
    if name == "linear":
        from engram.plugins.linear import LinearMiner
        return LinearMiner()
    raise ValueError(f"Unknown plugin '{name}'. Available: obsidian | notion | linear")


__all__ = ["PluginMiner", "get_plugin"]
