#!/usr/bin/env bash
# Engram pre-compact hook for Claude Code (PreCompact).
#
# Runs before Claude Code compacts the conversation and mines the session
# transcript into the château so nothing is lost.
#
# Install with `engram install-hooks`, which copies this script to
# ~/.engram/hooks/ and prints the settings.json snippet:
#   {
#     "hooks": {
#       "PreCompact": [
#         {
#           "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_precompact_hook.sh"}]
#         }
#       ]
#     }
#   }
#
# Claude Code sends JSON on stdin with "transcript_path", the session's
# JSONL transcript. Messages are stored with stable IDs, so compacting the
# same session again only adds what is new.
#
# Environment: ENGRAM_PYTHON (set by install-hooks), ENGRAM_WING (default: the
# project folder or git repo name), ENGRAM_ROOM (default
# "conversation").

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

TRANSCRIPT=$("$PY" -c '
import json, sys
try:
    d = json.loads(sys.argv[1] or "{}")
except ValueError:
    sys.exit(0)
print(d.get("transcript_path") or "")
' "$PAYLOAD" 2>/dev/null || true)

if [ -z "$TRANSCRIPT" ]; then
    exit 0
fi
TRANSCRIPT="${TRANSCRIPT/#\~/$HOME}"
if [ ! -f "$TRANSCRIPT" ]; then
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
ROOM="${ENGRAM_ROOM:-conversation}"

"${ENGRAM[@]}" mine "$TRANSCRIPT" --wing "$WING" --room "$ROOM" --mode convos >/dev/null 2>&1 || true

# Rebuild L1 so the next session starts with updated facts
"${ENGRAM[@]}" wake-up --rebuild >/dev/null 2>&1 || true

exit 0
