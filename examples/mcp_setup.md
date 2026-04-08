# Engram MCP Setup

## Starting the server

```bash
python -m engram.mcp_server
```

## Claude Desktop config

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "engram": {
      "command": "python",
      "args": ["-m", "engram.mcp_server"]
    }
  }
}
```

## Available tools (22)

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
