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
# Environment: ENGRAM_WING (default "default"), ENGRAM_ROOM (default
# "conversation").

set -uo pipefail

if ! command -v engram &>/dev/null || ! command -v python3 &>/dev/null; then
    exit 0
fi

PAYLOAD=$(cat 2>/dev/null || true)

TRANSCRIPT=$(python3 -c '
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

WING="${ENGRAM_WING:-default}"
ROOM="${ENGRAM_ROOM:-conversation}"

engram mine "$TRANSCRIPT" --wing "$WING" --room "$ROOM" --mode convos >/dev/null 2>&1 || true

# Rebuild L1 so the next session starts with updated facts
engram wake-up --rebuild >/dev/null 2>&1 || true

exit 0
