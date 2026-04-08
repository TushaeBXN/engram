# Engram

> **The AI memory layer that never forgets.**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-106%20passed-brightgreen)]()

Engram is a **local-first, open-source AI memory system**. It solves one problem: AI sessions end, but your work doesn't. Every decision, debug session, and architecture choice you've had with an AI disappears the moment the conversation closes. Engram makes it permanent, searchable, and retrievable in ~170 tokens.

Everything lives on your machine. No cloud. No API key required to run.

---

## Benchmark Targets

| Benchmark            | Metric              | Target    |
|----------------------|---------------------|-----------|
| LongMemEval          | Single-session QA   | ≥ 0.68 F1 |
| LongMemEval          | Multi-session QA    | ≥ 0.61 F1 |
| LoCoMo               | Entity recall       | ≥ 0.72    |
| LoCoMo               | Event recall        | ≥ 0.69    |
| ES compression       | Factual paragraphs  | 8–10×     |
| ES compression       | Code-heavy content  | 4–6×      |
| ES compression       | Mixed               | ~6×       |
| Cold-start context   | L0 + L1 tokens      | ≤ 170     |
| Search latency p99   | ChromaDB 100k       | < 200ms   |
| Search latency p99   | FAISS 100k          | < 50ms    |

---

## Quick Start

```bash
# Install
pip install engram

# Or with optional backends
pip install "engram[faiss]"       # FAISS speed backend
pip install "engram[sqlitevec]"   # zero-dependency fallback
pip install "engram[all]"         # everything

# Initialise your memory château
engram init ~/myproject

# Mine a project directory
engram mine ~/myproject --wing myapp

# Mine a conversation export
engram mine ~/Downloads/claude-export --mode convos --wing myapp

# Search
engram search "auth migration decisions" --wing myapp

# Load cold-start context (~170 tokens)
engram wake-up
```

---

## Memory Château Architecture

```
Wing  (person or project)
  └── Room  (named topic: "auth-migration", "ci-pipeline")
        ├── Hall  (memory type: facts | events | discoveries | preferences | advice)
        │     ├── Closet  (ES-compressed summary — fast AI read)
        │     └── Drawer  (verbatim original — never summarised)
        └── Tunnel  (cross-wing link when same room spans multiple wings)
```

### Memory Layers

| Layer | Content                        | Size       | When Loaded              |
|-------|--------------------------------|------------|--------------------------|
| L0    | Identity — who is this AI?     | ~50 tokens | Always                   |
| L1    | Critical facts in ES           | ~120 tokens| Always                   |
| L2    | Room recall — current project  | On demand  | When topic arises        |
| L3    | Deep semantic search           | On demand  | When explicitly queried  |

Total cold-start context: **~170 tokens** (L0 + L1 only).

---

## Using with Claude via MCP

Start the MCP server:

```bash
python -m engram.mcp_server
```

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

Claude will then have access to all 22 `engram_*` tools including `engram_wake_up`,
`engram_search`, `engram_add_memory`, `engram_kg_add`, `engram_replay`, and more.

See [`examples/mcp_setup.md`](examples/mcp_setup.md) for the full tool list.

---

## Using with Local Models

Engram works entirely offline. The vector backends use local embeddings:

```python
from engram.backends import get_backend
from engram.palace import Palace
from engram.searcher import Searcher

palace = Palace()
backend = get_backend("chromadb")   # or "faiss" / "sqlitevec"
searcher = Searcher(backend, palace)

results = searcher.search("auth migration")
for r in results:
    print(r["text"], r["final_score"])
```

No model API required. ChromaDB embeds locally using its bundled models.

---

## Full CLI Reference

### Setup

```bash
engram init <dir>                              # guided onboarding + ES bootstrap
```

### Mining

```bash
engram mine <dir>                              # mine project files
engram mine <dir> --mode convos                # mine conversation exports
engram mine <dir> --mode convos --wing myapp   # tag with a wing
engram mine <dir> --since 2026-01-01           # skip files older than date
engram mine <dir> --plugin obsidian            # use Obsidian vault plugin
engram mine <dir> --plugin notion              # Notion export
engram mine <dir> --plugin linear              # Linear issues export
```

### Watch Mode

```bash
engram watch <dir>                             # auto-mine on file changes
engram watch <dir> --wing myapp --mode convos  # tag + conversation mode
```

### Search

```bash
engram search "query"
engram search "query" --wing myapp
engram search "query" --room auth-migration
engram search "query" --no-decay               # disable recency weighting
engram search "query" --results 20             # max results
```

### Memory Stack

```bash
engram wake-up                                 # L0 + L1 context dump (~170 tokens)
engram wake-up --wing myapp                    # wing-scoped L1
engram wake-up --rebuild                       # rebuild L1 from drawers
```

### Compression

```bash
engram compress                                # ES compress all closets
engram compress --wing myapp                   # wing-scoped
engram compress --wing myapp --room auth       # room-scoped
```

### Knowledge Graph

```bash
engram kg query "Kai"
engram kg query "Kai" --all                    # include expired triples
engram kg add "Kai" works_on "Orion" --from 2025-06-01
engram kg invalidate "Kai" works_on "Orion" --ended 2026-03-01
engram kg timeline "auth-migration"
```

### Maintenance

```bash
engram conflicts                               # interactive TUI conflict resolver
engram audit                                   # health check
engram audit --fix                             # auto-resolve safe issues
engram replay --room auth-migration            # chronological room story
engram replay --room auth-migration --wing myapp
engram status                                  # château overview
engram split <dir>                             # split concatenated transcripts
engram split <dir> --dry-run
```

---

## Configuration

**`~/.engram/config.json`**

```json
{
  "palace_path": "~/.engram/palace",
  "vector_backend": "chromadb",
  "decay_factor": 0.005,
  "decay_max_days": 90,
  "collection_name": "engram_drawers",
  "people_map": {}
}
```

| Key              | Default              | Description                                           |
|------------------|----------------------|-------------------------------------------------------|
| `palace_path`    | `~/.engram/palace`   | Root of the château filesystem                        |
| `vector_backend` | `chromadb`           | `chromadb` \| `faiss` \| `sqlitevec`                  |
| `decay_factor`   | `0.005`              | Recency boost per day: `score * (1 + factor * days)` |
| `decay_max_days` | `90`                 | Days after which decay levels off                     |
| `collection_name`| `engram_drawers`     | ChromaDB collection name                              |

**`~/.engram/identity.txt`** — plain text, becomes your L0 context.

**`~/.engram/wing_config.json`** — generated by `engram init`.

---

## Module Reference

| File                          | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `engram/palace.py`            | Wing/Room/Hall/Closet/Drawer data model             |
| `engram/config.py`            | Config loading, `~/.engram/` management             |
| `engram/shorthand.py`         | Engram Shorthand (ES) compression dialect           |
| `engram/knowledge_graph.py`   | Temporal KG, SQLite backend                         |
| `engram/miner.py`             | Project file ingest pipeline                        |
| `engram/convo_miner.py`       | Conversation export ingest (Claude, ChatGPT, Slack) |
| `engram/searcher.py`          | Semantic search + recency weighting                 |
| `engram/layers.py`            | L0–L3 memory stack                                  |
| `engram/watcher.py`           | FSEvents/inotify watch mode                         |
| `engram/conflict.py`          | Contradiction detection + TUI resolver              |
| `engram/audit.py`             | Memory health audit                                 |
| `engram/replay.py`            | Session/room replay                                 |
| `engram/agents.py`            | Specialist agent diary system                       |
| `engram/palace_graph.py`      | Room navigation graph                               |
| `engram/onboarding.py`        | Guided init + ES bootstrap                          |
| `engram/cli.py`               | Typer CLI entry point                               |
| `engram/mcp_server.py`        | MCP server — 22 tools                               |
| `engram/backends/base.py`     | Abstract VectorBackend interface                    |
| `engram/backends/chromadb_backend.py` | ChromaDB backend (default)                |
| `engram/backends/faiss_backend.py`    | FAISS backend (speed-optimised)           |
| `engram/backends/sqlitevec_backend.py`| sqlite-vec backend (zero-dependency)     |
| `engram/plugins/obsidian.py`  | Obsidian vault plugin miner                         |
| `engram/plugins/notion.py`    | Notion export plugin miner                          |
| `engram/plugins/linear.py`    | Linear issues plugin miner                          |
| `engram/hooks/engram_save_hook.sh` | Claude Code auto-save hook                    |
| `engram/hooks/engram_precompact_hook.sh` | Claude Code pre-compact hook             |

---

## Engram Shorthand (ES)

ES is a lossless compression dialect that any LLM can read without a decoder.

```python
from engram.shorthand import compress, decompress

text = (
    "The authentication module is a critical component that has a dependency "
    "on the database and is responsible for verifying user credentials."
)

es = compress(text, confidence=4)
# → "auth module:★★ component + dependency db & responsible verifying user credentials [★★★★]"

decompress(es)
# → expands symbols back to natural language

# Code-aware compression
code = "def authenticate(user: str, token: str) -> bool:"
compress(code, is_code=True)
# → "fn:authenticate(user:str,token:str)->bool"

# Diff notation
compress("+add_middleware()\n-manual_verify()", is_diff=True, diff_filename="auth.py")
# → "CHANGE:auth.py add:add_middleware() rm:manual_verify()"
```

---

## Recency Weighting

```
final_score = semantic_score × (1 + recency_boost)
recency_boost = decay_factor × max(0, decay_max_days − age_days)
```

Pinned drawers (`engram_pin`) bypass decay entirely.

---

## Claude Code Hooks

Copy hooks to `~/.engram/hooks/` then add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit",
      "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_save_hook.sh"}]
    }],
    "PreCompact": [{
      "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_precompact_hook.sh"}]
    }]
  }
}
```

Set `ENGRAM_WING=myapp` and `ENGRAM_ROOM=current-task` in your environment.

---

## Requirements

- Python 3.9+
- chromadb ≥ 0.4.0
- typer ≥ 0.9.0
- rich ≥ 13.0.0
- watchdog ≥ 3.0.0
- questionary ≥ 2.0.0
- pyyaml ≥ 6.0

Optional:
- `faiss-cpu` — FAISS backend
- `sqlite-vec` — sqlite-vec backend

No API key. No internet after install.

---

## Contributing

1. Fork the repo
2. `pip install -e ".[dev]"`
3. `pre-commit install`
4. Run tests: `pytest tests/ -v`
5. Submit a PR

---

## License

MIT © 2026 Tushae Thomas
