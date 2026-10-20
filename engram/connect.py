"""Connect Engram to AI apps: ``engram connect <app>``.

Each app keeps its MCP servers in its own settings file, under its own key.
This module knows where, adds an ``engram`` entry that runs the MCP server
with the Python that has Engram installed (so PATH doesn't matter), keeps a
``.bak`` copy, and leaves every other setting alone. Running it again changes
nothing.

Apps whose settings can't be edited safely (Zed's settings allow comments;
LM Studio's file moves between versions) get the exact snippet to paste.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SERVER_NAME = "engram"


def server_command() -> tuple[str, list[str]]:
    """The command and arguments that start Engram's MCP server."""
    return sys.executable, ["-m", "engram.mcp_server"]


def _app_support() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


@dataclass
class App:
    key: str          # what you type: engram connect <key>
    name: str         # shown to people
    path: Path        # settings file
    kind: str         # "json" (servers under `container`), "toml" (Codex) or "manual"
    container: str = "mcpServers"
    entry_extra: Optional[dict] = None   # extra fields some apps require
    restart: str = "Restart the app"


def apps() -> dict[str, App]:
    home = Path.home()
    support = _app_support()
    found = [
        App("claude-desktop", "Claude Desktop", support / "Claude" / "claude_desktop_config.json", "json",
            restart="Quit and reopen Claude Desktop"),
        App("cursor", "Cursor", home / ".cursor" / "mcp.json", "json",
            restart="Fully quit and reopen Cursor"),
        App("windsurf", "Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json", "json",
            restart="Restart Windsurf"),
        App("vscode", "VS Code (Copilot agent mode)", support / "Code" / "User" / "mcp.json", "json",
            container="servers", entry_extra={"type": "stdio"},
            restart="Reload VS Code, then enable the engram server in the Copilot chat tools list"),
        App("gemini", "Gemini CLI", home / ".gemini" / "settings.json", "json",
            restart="Start a new Gemini CLI session"),
        App("codex", "Codex CLI", home / ".codex" / "config.toml", "toml",
            restart="Start a new Codex session"),
        App("zed", "Zed", home / ".config" / "zed" / "settings.json", "manual", container="context_servers",
            restart="Zed picks it up after you save settings"),
        App("lm-studio", "LM Studio", home / ".lmstudio" / "mcp.json", "manual",
            restart="In LM Studio: Program tab → Install → Edit mcp.json, paste, save"),
    ]
    return {a.key: a for a in found}


def entry(app: App) -> dict:
    command, args = server_command()
    return {**(app.entry_extra or {}), "command": command, "args": args}


def snippet(app: App) -> str:
    """What to paste by hand into the app's settings."""
    if app.kind == "toml":
        return _toml_block()
    return json.dumps({app.container: {SERVER_NAME: entry(app)}}, indent=2)


def _toml_block() -> str:
    command, args = server_command()
    return (f"[mcp_servers.{SERVER_NAME}]\n"
            f"command = {json.dumps(command)}\n"
            f"args = {json.dumps(args)}\n")


def _backup(path: Path) -> None:
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))


def connect(app: App) -> str:
    """Add Engram to *app*'s settings. Returns "added", "updated" or "unchanged".

    Raises ValueError (file left untouched) when the existing settings can't be
    read safely; the caller then shows the snippet to paste by hand.
    """
    if app.kind == "manual":
        raise ValueError(f"{app.name}'s settings are best edited by hand")
    path = app.path
    if app.kind == "toml":
        text = path.read_text() if path.exists() else ""
        header = f"[mcp_servers.{SERVER_NAME}]"
        if header in text:
            if _toml_block() in text:
                return "unchanged"
            raise ValueError(f"{path} already has an {header} section; update it by hand")
        path.parent.mkdir(parents=True, exist_ok=True)
        _backup(path)
        sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + _toml_block())
        return "added"
    settings: dict = {}
    if path.exists() and path.read_text().strip():
        try:
            settings = json.loads(path.read_text())
        except ValueError as exc:
            raise ValueError(f"{path} isn't plain JSON ({exc})") from exc
        if not isinstance(settings, dict):
            raise ValueError(f"{path} doesn't hold a JSON object")
    servers = settings.setdefault(app.container, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: '{app.container}' isn't an object")
    wanted = entry(app)
    if servers.get(SERVER_NAME) == wanted:
        return "unchanged"
    status = "updated" if SERVER_NAME in servers else "added"
    servers[SERVER_NAME] = wanted
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return status


def detected() -> list[App]:
    """Apps that look installed (their settings folder exists)."""
    return [a for a in apps().values() if a.path.parent.exists()]
