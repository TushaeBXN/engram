# Engram
<img width="1408" height="768" alt="Gemini_Generated_Image_9nr9z59nr9z59nr9" src="https://github.com/user-attachments/assets/e04422f2-1974-48c2-8568-238bc2641bdf" />


> **Small, private, verbatim memory for your AI — set up in a minute, readable in an afternoon.**

**98.2% R@5 on LongMemEval with no AI model and no API calls: ahead of MemPalace's raw mode (96.6%) and within one question of its best no-model score (98.4%). Free, local, one `pip install`.** ([results](#engram-and-mempalace))

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![CI](https://github.com/TushaeBXN/engram/actions/workflows/ci.yml/badge.svg)](https://github.com/TushaeBXN/engram/actions/workflows/ci.yml)

Engram gives Claude (and any MCP client) a long-term memory that lives on your machine. It keeps every note, file and conversation **word for word**, organises them into wings and rooms, and finds them again with semantic search. No cloud, no API key, no account.

## Why Engram

- **Small enough to read.** About 6,300 lines of Python in 33 files. You can audit everything that touches your data in an afternoon.
- **Two commands to set up.** Install, run `engram install-hooks`, and Claude Code saves your work and conversations automatically.
- **Verbatim, not summarised.** Drawers store your original text. Compression is only used for the small context Engram loads into a model.
- **Private by default.** Everything stays under `~/.engram/`. Nothing is sent anywhere.
- **Honest numbers.** Benchmarks are reproducible from this repo, and unmeasured goals are labelled as goals ([details](#benchmark-targets)).

## Set up in 60 seconds

```bash
pip install engram-chateau                            # Python 3.9+ (or: uv tool install engram-chateau)
engram init ~/myproject                                # create your memory château
engram install-hooks                                   # auto-save from Claude Code (prints a settings.json snippet)
claude mcp add engram -- python -m engram.mcp_server   # give Claude the 22 engram_* tools
```

Then ask Claude to search or remember things, or use the CLI: `engram mine ~/myproject --wing myapp`, `engram search "auth decisions"`.

## Engram and MemPalace

Engram's design (wings, rooms, halls, drawers, a temporal knowledge graph) is inspired by [MemPalace](https://github.com/MemPalace/mempalace), a much larger and more mature project. Engram aims to be the small one: the same core ideas in a codebase one person can read, with a two-line setup. Here is how the two compare on LongMemEval (500 questions, session-level R@5: is the right conversation in the top 5 results?):

| LongMemEval R@5 | Engram | MemPalace |
|---|---|---|
| Semantic search only, no AI model | **96.8%** | 96.6% |
| Hybrid: keywords only, no AI model | 97.4% | — |
| Hybrid: keywords + time + preferences, no AI model | **98.2%** (Engram's default) | **98.4%** (hybrid v4, held-out 450 questions) |
| Hybrid + AI reranking | not offered | ≥ 99% |
| R@10, default setup | **99.2%** | — |

Engram's numbers come from one full run each on a Mac mini with the default local embedding model (all-MiniLM-L6-v2); MemPalace's are from [its README](https://github.com/MemPalace/mempalace#benchmarks). The setups differ, so read this as "level on raw retrieval":

- Engram indexes assistant messages as well as yours; MemPalace's raw mode indexes your messages only. That is why Engram answers every "what did you tell me about…" question.
- Both hybrids boost keywords, times the question names and preferences you mentioned. Engram's versions are general rules written without looking at the benchmark's missed questions, and are scored on all 500 questions; MemPalace's v4 was tuned on 50 questions and scored on the other 450.
- One question is worth 0.2 points: 98.2% vs 98.4% is one question.

On **LoCoMo** (10 long conversations, 1,986 questions, session-level R@10: share of the sessions holding the answer that are in the top 10 results), measured the same way MemPalace measures it:

| LoCoMo R@10 | Engram | MemPalace |
|---|---|---|
| Semantic search only, no AI model | **84.4%** | 60.3% |
| Hybrid, no AI model | 87.4% (Engram's default) | **88.9%** (hybrid v5) |
| Hybrid R@5 | 78.3% | **83.7%** |

Engram's raw retrieval is 24 points ahead here because it indexes every message (split into chunks) rather than one embedding per session, which the embedding model truncates. MemPalace's LoCoMo hybrid is ahead by 1.5 points at R@10 and 5.4 at R@5; it adds a person-name boost, a quoted-phrase boost and a heavier keyword weight on top of what Engram does. Engram's LoCoMo run uses its LongMemEval defaults unchanged.

MemPalace also publishes ConvoMem and MemBench results and offers LLM reranking, a shared memory hub across machines and Docker images; Engram has none of those yet. Every Engram number above is reproducible with the commands in [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md).

---

## Why local memory?

| | Engram | Cloud memory tools |
|---|---|---|
| Cold-start context | Designed for **~170 tokens** (L0 + L1, not yet measured) | Varies |
| Install | One `pip install engram-chateau` | Often Docker + cloud signup |
| API key required | **No** | Usually |
| Data leaves your machine | **Never** | Yes |
| Compression | **ES shorthand** for context (~1.6× on prose) | — |
| Open source | **MIT** | Often proprietary |

---

## Benchmark Targets

LongMemEval, LoCoMo and ES compression are measured. On LongMemEval (500 questions, all-MiniLM-L6-v2 on ChromaDB, no LLM, no reranker, no API calls) Engram's default search puts the right session in the top 5 for **98.2%** of questions and in the top 10 for 99.2% (semantic search alone: 96.8% and 98.6%). On LoCoMo it reaches 87.4% session R@10 (semantic alone: 84.4%). See [Engram and MemPalace](#engram-and-mempalace) for the comparison, and [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md) for the per-type breakdown and how to reproduce.

| Benchmark            | Metric              | Target    | Status                  |
|----------------------|---------------------|-----------|-------------------------|
| LongMemEval          | Session recall R@5  | ≥ 0.95    | 0.982 measured          |
| LongMemEval          | Session recall R@10 | ≥ 0.97    | 0.992 measured          |
| LoCoMo               | Session recall R@10 | ≥ 0.85    | 0.874 measured          |
| LoCoMo               | Session recall R@5  | ≥ 0.75    | 0.783 measured          |
| ES compression       | Factual paragraphs  | ≥ 1.5×    | 1.6× measured           |
| ES compression       | Code-heavy content  | ≥ 1.1×    | 1.1× measured           |
| ES compression       | Mixed               | ≥ 1.4×    | 1.5× measured           |
| Cold-start context   | L0 + L1 tokens      | ≤ 170     | Not yet measured        |
| Search latency p99   | ChromaDB 100k       | < 200ms   | Not yet measured        |
| Search latency p99   | FAISS 100k          | < 50ms    | Not yet measured        |

---

## Quick Start

> **Note:** Engram is published on PyPI as **`engram-chateau`**; the command and `import engram` are just `engram`. The package named `engram` on PyPI is an unrelated project.

```bash
# Install
pip install engram-chateau                 # or: uv tool install engram-chateau
pip install git+https://github.com/TushaeBXN/engram   # latest unreleased code from main

# Or with optional backends
pip install "engram-chateau[faiss]"         # FAISS speed backend
pip install "engram-chateau[sqlitevec]"     # zero-dependency fallback
pip install "engram-chateau[viz]"           # graph visualisation (matplotlib + networkx)
pip install "engram-chateau[all]"           # everything

# Initialise your memory château
engram init ~/myproject

# Mine a project directory
engram mine ~/myproject --wing myapp

# Mine a conversation export
engram mine ~/Downloads/claude-export --mode convos --wing myapp

# Search
engram search "auth migration decisions" --wing myapp

# Answer a question grounded in memory (uses Ollama if available)
engram answer "What did we decide about the auth strategy?" --wing myapp

# Store a typed, validated memory
engram remember-type "Always prefer float32 on CPU because bfloat16 is unsupported" \
  instruction --wing myapp --confidence 0.95

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

Mined notes and conversation messages are sorted into halls by their **content** (e.g. "I prefer…" → preferences, "turns out the root cause…" → discoveries) using a local, rule-based classifier (`engram/classifier.py`). Code and config files keep their extension-based hall; when nothing matches clearly, the old extension/role default is used.

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

**Claude Code:**

```bash
claude mcp add engram -- python -m engram.mcp_server
```

**Claude Desktop:** add this to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

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

Use the full path to the Python that has Engram installed if `python` on your PATH is a different one.

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
engram search "query" --no-hybrid              # semantic only (keyword boost is on by default)
engram search "query" --rerank                 # reorder the top results with the local reranker (optional)
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

### Answer (LLM-grounded QA)

```bash
engram answer "What auth approach did we choose?"
engram answer "What did we decide about the DB?" --wing myapp
engram answer "Why did we drop Redis?" --model llama3.2 --chunks 8
```

### Typed Memory

```bash
# Store a categorised, validated memory
engram remember-type "Prefer SQLite for local dev" preference --wing myapp
engram remember-type "Use float32 on CPU because bfloat16 unsupported" \
  instruction --wing anthos --confidence 0.95

# List all 13 valid types
engram remember-type --list
```

### Provenance

```bash
engram provenance <drawer-id>                  # provenance record for one memory
engram provenance <drawer-id> --history        # full version chain
engram provenance --summary                    # source counts across château
```

### Graph Visualisation

```bash
pip install "engram-chateau[viz]"
engram graph                                   # all wings → memory_graph.png
engram graph --wing myapp --output myapp.png   # scoped to one wing
```

### Maintenance

```bash
engram conflicts                               # interactive TUI conflict resolver
engram audit                                   # health check
engram audit --fix                             # auto-resolve safe issues
engram replay --room auth-migration            # chronological room story
engram replay --room auth-migration --wing myapp
engram replay --room auth-migration --type decision          # filter by type
engram replay --room auth-migration --since 2026-06-01       # filter by date
engram replay --room auth-migration --min-confidence 0.8     # filter by confidence
engram status                                  # château overview
engram split <dir>                             # split concatenated transcripts
engram split <dir> --dry-run
```

---

## Configuration

**`~/.engram/config.json`**

```json
{
  "chateau_path": "~/.engram/chateau",
  "vector_backend": "chromadb",
  "decay_factor": 0.005,
  "decay_max_days": 90,
  "hybrid_weight": 0.3,
  "temporal_weight": 0.4,
  "preference_summaries": true,
  "collection_name": "engram_drawers",
  "people_map": {}
}
```

| Key              | Default              | Description                                           |
|------------------|----------------------|-------------------------------------------------------|
| `chateau_path`   | `~/.engram/chateau`  | Root of the château filesystem                        |
| `vector_backend` | `chromadb`           | `chromadb` \| `faiss` \| `sqlitevec`                  |
| `decay_factor`   | `0.005`              | Recency boost per day: `score * (1 + factor * days)` |
| `decay_max_days` | `90`                 | Days after which decay levels off                     |
| `hybrid_weight`  | `0.3`                | Keyword boost for hybrid search: `score * (1 + weight * overlap)`; `0` for semantic only (CLI and MCP) |
| `temporal_weight`| `0.4`                | Boost for memories dated near a time the query names ("two weeks ago"); `0` to turn off |
| `preference_summaries` | `true`         | Index a "User has mentioned: …" summary with user messages that state preferences or concerns (applies to newly mined conversations) |
| `reranker`       | `false`              | Reorder the top results with a local cross-encoder (ms-marco-MiniLM, ONNX, no API key). The first use downloads a ~90 MB model to `~/.engram/models/`; while `false`, Engram makes no network calls for it |
| `rerank_top`     | `20`                 | How many top results the reranker reorders |
| `collection_name`| `engram_drawers`     | ChromaDB collection name                              |

`ENGRAM_VECTOR_BACKEND` overrides `vector_backend` for a single run without editing the file, e.g. `ENGRAM_VECTOR_BACKEND=sqlitevec engram search "auth"`.

### Troubleshooting: ChromaDB fails to load

ChromaDB 1.x ships compiled Rust bindings (`chromadb_rust_bindings`). If they don't match your Python or platform, Engram prints a `ChromaDB failed to load` message instead of starting. Fix it by reinstalling (`pip install --force-reinstall --no-cache-dir chromadb`) or by switching to the `sqlitevec` backend, which needs no compiled dependencies. Each backend keeps its own index, so re-run `engram mine` after switching.

**`~/.engram/identity.txt`** — plain text, becomes your L0 context.

**`~/.engram/wing_config.json`** — generated by `engram init`.

---

## Module Reference

| File                          | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `engram/chateau.py`           | Wing/Room/Hall/Closet/Drawer data model             |
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
| `engram/qa.py`                | LLM-grounded QA over memory (Ollama + fallback)     |
| `engram/typed_memory.py`      | 13-type typed memory with validation + ES storage   |
| `engram/provenance.py`        | Memory provenance and version-chain tracking        |
| `engram/agents.py`            | Specialist agent diary system                       |
| `engram/chateau_graph.py`     | Room navigation graph                               |
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

ES is a compact shorthand that any LLM can read without a decoder. It is used for the context Engram loads into a model (L1 facts, closets); drawers always keep your original text. ES is lossy: filler words such as "the" and "that" are dropped, and `decompress()` only expands unambiguous symbols such as `∴` and `→`. Expect about 1.6× on prose and 1.1× on code.

```python
from engram.shorthand import compress, decompress

text = (
    "The authentication module is a critical component that has a dependency "
    "on the database and is responsible for verifying user credentials."
)

es = compress(text, confidence=4)
# → "auth module=★★ component +dep on db&owns: verifying user credentials. [★★★★]"

decompress(es)
# → expands unambiguous symbols (∴, →, ¬ …) back to words

# Code-aware compression
code = "def authenticate(user: str, token: str) -> bool:"
compress(code, is_code=True)
# → "fn:authenticate(user: str,token: str)->bool"

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

Two hooks keep Engram up to date while you work in Claude Code:

- **Save hook** (PostToolUse): every file Claude writes or edits is mined into the château. Re-saving a file replaces its drawer instead of adding a duplicate.
- **Pre-compact hook** (PreCompact): before Claude Code compacts a conversation, the session transcript is mined so nothing is lost. Only user and assistant text is stored, not tool calls, tool output or thinking, and running it again on the same session adds no duplicates.

```bash
engram install-hooks   # copies the scripts to ~/.engram/hooks/ and prints the settings snippet
```

Merge the printed snippet into `~/.claude/settings.json`. It looks like:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit|MultiEdit",
      "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_save_hook.sh"}]
    }],
    "PreCompact": [{
      "hooks": [{"type": "command", "command": "~/.engram/hooks/engram_precompact_hook.sh"}]
    }]
  }
}
```

Optional environment variables: `ENGRAM_WING` (default `default`), `ENGRAM_ROOM` for transcripts (default `conversation`), `ENGRAM_AGENT` for diary entries (default `claude-code`).

---

## Web UI (notes)

```bash
engram ui          # opens http://127.0.0.1:7741 in your browser
```
<img width="1126" height="932" alt="Engram notes UI with knowledge graph" src="https://github.com/user-attachments/assets/870d76e7-bdc3-42a5-9056-6a54a1dd7ef1" />

A local notes app with a force-directed graph of your notes and their `[[wikilinks]]`: wing tabs, `#tag` filters, pinned notes, a daily journal, a Markdown editor, and JSON export/import.

> **Note:** the UI keeps its notes in your browser's local storage. It does not yet show the memories Engram stores in `~/.engram/` (mined files, conversations, MCP memories). Use `engram search`, `engram replay` or the MCP tools for those.

---

## Requirements

- Python 3.9+
- chromadb ≥ 1.0 on Python 3.9–3.14, installed automatically. On Python 3.15+ (no onnxruntime build yet) Engram installs without it and uses the built-in sqlitevec backend; use Python 3.11–3.14 for semantic search.
- typer ≥ 0.9.0
- rich ≥ 13.0.0
- watchdog ≥ 3.0.0
- questionary ≥ 2.0.0
- pyyaml ≥ 6.0

Optional:
- `faiss-cpu` — FAISS backend
- `sqlite-vec` — sqlite-vec backend
- `matplotlib` + `networkx` — graph visualisation (`pip install "engram-chateau[viz]"`)
- `requests` — Ollama API calls for `engram answer`

No API key. No internet after install.

---

## Contributing

1. Fork the repo
2. `pip install -e ".[dev]"`
3. `pre-commit install`
4. Run tests: `pytest tests/ -v`
5. Submit a PR

### Releasing

Engram is published to PyPI as **`engram-chateau`** (the command and `import engram` are unchanged). Publishing runs from `.github/workflows/publish.yml` using PyPI trusted publishing, so no API token is stored anywhere.

The trusted publisher is configured on pypi.org for project `engram-chateau`: owner `TushaeBXN`, repository `engram`, workflow `publish.yml`, environment `pypi`.

To release: bump `version` in `pyproject.toml` and `__version__` in `engram/__init__.py`, merge, then publish a GitHub release tagged `v<version>` with the dots kept (for example `v1.3.0`, not `v1.30`). The workflow checks the tag matches both, runs the tests, builds, and uploads.

---

## License

MIT © 2026 Tushae Thomas
