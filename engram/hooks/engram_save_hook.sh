#!/usr/bin/env bash
# Engram auto-save hook for Claude Code (PostToolUse).
#
# Install with `engram install-hooks`, which copies this script to
# ~/.engram/hooks/ and prints the settings.json snippet:
#   {
#     "hooks": {
#       "PostToolUse": [
#         {
#           "matcher": "Write|Edit|MultiEdit",
#           "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_save_hook.sh"}]
#         }
#       ]
#     }
#   }
#
# What it does:
#   1. Reads the hook payload Claude Code sends on stdin (JSON with
#      tool_input.file_path).
#   2. Mines the written file into the château. Re-mining the same file
#      replaces its drawer, so repeated edits don't create duplicates.
#   3. Writes a diary entry for the agent.
#
# Environment: ENGRAM_PYTHON (set by install-hooks), ENGRAM_WING (default: the
# project folder or git repo name), ENGRAM_AGENT (default
# "claude-code"). The hook never fails the tool call: errors are ignored.

set -uo pipefail

# The Python that has Engram: ENGRAM_PYTHON (set by `engram install-hooks`),
# else an `engram` command on PATH with python3.
if [ -n "${ENGRAM_PYTHON:-}" ]; then
    PY="$ENGRAM_PYTHON"
    ENGRAM=("$PY" -m engram)
elif command -v engram &>/dev/null && command -v python3 &>/dev/null; then
    PY=python3
    ENGRAM=(engram)
else
    exit 0  # Engram not installed in this environment
fi

PAYLOAD=$(cat 2>/dev/null || true)

# tool_input.file_path (current Claude Code); top-level file_path as a fallback.
FILE_PATH=$("$PY" -c '
import json, sys
try:
    d = json.loads(sys.argv[1] or "{}")
except ValueError:
    sys.exit(0)
print((d.get("tool_input") or {}).get("file_path") or d.get("file_path") or "")
' "$PAYLOAD" 2>/dev/null || true)

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

# Wing: ENGRAM_WING, else the project you're working in (git repo or folder name).
CWD=$("$PY" -c '
import json, sys
try:
    print((json.loads(sys.argv[1] or "{}")).get("cwd") or "")
except ValueError:
    pass
' "$PAYLOAD" 2>/dev/null || true)
WING="${ENGRAM_WING:-$("$PY" -c '
import sys
from engram.recall import project_wing
print(project_wing(sys.argv[1] or None) or "default")
' "${CWD:-$PWD}" 2>/dev/null || echo default)}"
[ -n "$WING" ] || WING=default
AGENT="${ENGRAM_AGENT:-claude-code}"

"${ENGRAM[@]}" mine "$FILE_PATH" --wing "$WING" >/dev/null 2>&1 || true

# Values are passed as arguments, never pasted into the Python source.
"$PY" -c '
import sys
from engram.agents import AgentDiary
AgentDiary(sys.argv[1]).write(f"Saved {sys.argv[2]} to château wing:{sys.argv[3]}")
' "$AGENT" "$FILE_PATH" "$WING" >/dev/null 2>&1 || true

exit 0
