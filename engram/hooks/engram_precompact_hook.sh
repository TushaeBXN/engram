#!/usr/bin/env bash
# Engram pre-compact hook for Claude Code.
#
# Runs before Claude Code compacts the conversation.  Mines the current
# conversation transcript into the château so nothing is lost.
#
# Install in ~/.claude/settings.json:
#   {
#     "hooks": {
#       "PreCompact": [
#         {
#           "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_precompact_hook.sh"}]
#         }
#       ]
#     }
#   }

set -euo pipefail

# Resolve engram
if ! command -v engram &>/dev/null; then
    exit 0
fi

WING="${ENGRAM_WING:-default}"
ROOM="${ENGRAM_ROOM:-conversation}"

# Read transcript from stdin (Claude Code passes the conversation JSON)
TRANSCRIPT_FILE=$(mktemp /tmp/engram_transcript_XXXXXX.json)
trap 'rm -f "$TRANSCRIPT_FILE"' EXIT

# Read stdin if available
if [ -t 0 ]; then
    # No stdin — nothing to compact
    exit 0
fi

cat > "$TRANSCRIPT_FILE"

if [ ! -s "$TRANSCRIPT_FILE" ]; then
    exit 0
fi

# Mine the transcript as a conversation export
engram mine "$TRANSCRIPT_FILE" \
    --wing "$WING" \
    --room "$ROOM" \
    --mode convos \
    2>/dev/null || true

# Rebuild L1 so the next session gets updated facts
engram wake-up --rebuild 2>/dev/null || true

exit 0
