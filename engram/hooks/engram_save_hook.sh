#!/usr/bin/env bash
# Engram auto-save hook for Claude Code.
#
# Install in ~/.claude/settings.json:
#   {
#     "hooks": {
#       "PostToolUse": [
#         {
#           "matcher": "Write|Edit",
#           "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_save_hook.sh"}]
#         }
#       ]
#     }
#   }
#
# What it does:
#   1. Reads the file path from CLAUDE_TOOL_INPUT (JSON from Claude Code)
#   2. Mines the written file into the active wing
#   3. Writes a diary entry for the current session agent

set -euo pipefail

# Resolve engram binary
ENGRAM="${HOME}/.local/bin/engram"
if ! command -v engram &>/dev/null && [ ! -x "$ENGRAM" ]; then
    # Not installed — skip silently
    exit 0
fi

# Read the tool input JSON from stdin (Claude Code passes it this way)
TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"
if [ -z "$TOOL_INPUT" ]; then
    # Try reading from stdin
    TOOL_INPUT=$(cat 2>/dev/null || echo "{}")
fi

# Extract file_path from JSON (requires jq or python)
FILE_PATH=""
if command -v jq &>/dev/null; then
    FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // empty' 2>/dev/null || true)
elif command -v python3 &>/dev/null; then
    FILE_PATH=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('file_path',''))" "$TOOL_INPUT" 2>/dev/null || true)
fi

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

# Determine wing from environment or config
WING="${ENGRAM_WING:-default}"

# Mine the file
engram mine "$FILE_PATH" --wing "$WING" 2>/dev/null || true

# Optionally write a diary entry
AGENT="${ENGRAM_AGENT:-claude-code}"
engram_agent_note="Saved $FILE_PATH to château wing:$WING"
# Diary write is best-effort — don't fail the hook if it errors
python3 -c "
from engram.agents import AgentDiary
AgentDiary('$AGENT').write('$engram_agent_note')
" 2>/dev/null || true

exit 0
