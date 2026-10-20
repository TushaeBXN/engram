# Engram MCP Setup

## Starting the server

```bash
engram-mcp                    # or: python -m engram.mcp_server
```

For Claude Code: `claude mcp add engram -- engram-mcp`. For Cursor, Windsurf, VS Code, Gemini CLI, Codex and Claude Desktop: `engram connect <app>`.

## Claude Desktop config

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram-mcp"
    }
  }
}
```

## Available tools (31)

| Tool | Description |
|------|-------------|
| `engram_search` | Semantic search with recency weighting |
| `engram_add_memory` | Store a new drawer |
| `engram_wake_up` | Load L0+L1 cold-start context |
| `engram_load_room` | Load L2 room context |
| `engram_compress` | ES compress text |
| `engram_decompress` | ES decompress text |
| `engram_kg_query` | KG entity lookup |
| `engram_kg_add` | Add KG triple |
| `engram_kg_invalidate` | Invalidate KG triple |
| `engram_kg_timeline` | Chronological entity timeline |
| `engram_list_wings` | List all wings |
| `engram_list_rooms` | List rooms in a wing |
| `engram_get_drawer` | Fetch a specific drawer |
| `engram_delete_drawer` | Delete a drawer |
| `engram_create_wing` | Create a new wing |
| `engram_create_room` | Create a new room |
| `engram_diary_write` | Write agent diary entry |
| `engram_diary_read` | Read agent diary |
| `engram_status` | Château stats |
| `engram_audit` | Health audit |
| `engram_replay` | Session replay |
| `engram_pin` | Pin a drawer (bypass decay) |
| `engram_correct` | Save a correction that replaces an outdated memory |
| `engram_supersede` | Mark one stored memory as replacing another (`undo` to reverse) |
| `engram_dispute` | Mark two memories as conflicting, undecided |
| `engram_history` | A memory's status and replacement history |
| `engram_recall` | The few memories clearly relevant to a message (auto-recall for any app) |
| `engram_link` | Link memories: `based_on`, `derived_from`, `contradicts`, `supersedes` (`undo` to remove) |
| `engram_source` | Record where a memory came from: user, primary, secondary, tool, inference |
| `engram_why` | Explain a memory: source, evidence (and whether it changed), earlier versions, conflicts, ranking |
| `engram_check` | What needs review: corrected evidence, unsupported inferences, open conflicts, broken links |
