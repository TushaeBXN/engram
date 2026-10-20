# Changelog

## 1.9.0

**Memories can explain themselves.**
- **Evidence links.** `engram link A based_on B` (B is evidence for A) and
  `A derived_from B` (A was inferred from B), stored in
  `chateau/relations.json`. `contradicts` and `supersedes` (or `updates`)
  use the existing correction ledger, so there is one vocabulary for every
  relationship. Links are checked: no missing memories, no evidence that
  leads back to itself, and repeating a link changes nothing.
- **Sources.** Every memory can say where it came from: `user`, `primary`,
  `secondary`, `tool` or `inference`, plus a citation or URL
  (`engram source`, or `source`/`source_ref` when saving). Older memories
  show "not recorded"; nothing is guessed. A correction keeps the old
  memory's source unless told otherwise.
- **`engram why <id>`** explains a memory: source and date, record or
  inference, the evidence tree (and whether any of it was since corrected or
  disputed), earlier versions with the evidence *they* rested on, what rests
  on this memory, conflicts, and with `--query` its rank and score parts.
- **`engram check`** lists what needs review: conclusions whose evidence was
  corrected or disputed, inferences with no evidence, unresolved conflicts,
  broken links. It never changes anything; an outdated position keeps the
  evidence it had.
- MCP: new tools `engram_link`, `engram_source`, `engram_why`, `engram_check`
  (31 tools); `engram_add_memory` takes `source`, `source_ref`, `based_on`
  and `derived_from`, and `engram_correct` takes `source` and `based_on`
  (all checked before anything is saved). The connect instructions tell the
  AI to record sources and evidence and to call `engram_why` before relying
  on a conclusion.
- Backups carry sources and evidence links (`relations`; backups from
  earlier versions import unchanged). Drawers without a source are written
  exactly as before, so older Engram versions read them unchanged.

## 1.8.0

**Engram for any AI app, not just Claude Code.**
- `engram connect <app>` adds Engram's MCP server to Claude Desktop, Cursor,
  Windsurf, VS Code (Copilot agent mode), Gemini CLI or Codex CLI, editing
  that app's own settings file (keeping everything else, with a `.bak`
  backup; running it again changes nothing). `engram connect all` does every
  installed app; `engram connect` lists them. Zed and LM Studio get the
  snippet to paste. The server runs with the Python that has Engram, so PATH
  doesn't matter.
- **Memory guidance for every client.** On connect, the MCP server now sends
  `instructions`: check memory (`engram_recall`) before answering anything
  that depends on past work, save decisions, and correct rather than
  contradict. Clients that pass server instructions to the model get Engram's
  "remember first" behaviour without a hook.
- New MCP tool `engram_recall`: the same filtered, project-aware recall the
  Claude Code hook uses, for any app (27 tools).

## 1.7.1

**Project-aware memory for Claude Code.**
- Auto-save and pre-compact now file memories under the project you're
  working in (the git repository's name, or the folder's), instead of one
  `default` wing, unless `ENGRAM_WING` is set. A `projects` setting maps
  folders to wings by hand.
- Auto-recall searches the current project first; memories from other
  projects appear only above `recall_other_min_relevance` (0.55). Memories
  already in `default` stay eligible. `engram recall --cwd FOLDER` previews it.

**Fix: hooks that silently did nothing.** The auto-save and pre-compact hooks
needed an `engram` command on PATH, which installs into a virtual environment
don't provide, so they exited without saving. `engram install-hooks` now
passes the Python that has Engram (`ENGRAM_PYTHON`), the hooks call
`python -m engram`, and re-running `engram install-hooks --apply` replaces
older Engram hook entries while keeping all your other hooks.

**MCP registry metadata.** `server.json` and the `mcp-name` marker in the
README let Engram be listed in the official MCP registry; a new
`engram-chateau` command starts the MCP server for clients that run the
package by name (`uvx engram-chateau`).

## 1.7.0

**Auto-recall for Claude Code** (`engram.recall`). A `UserPromptSubmit` hook
searches Engram each time you send Claude a message and, only when something
clearly matches, adds a short note to Claude's context: up to 3 memories
(`recall_max`), each trimmed, with where and when they're from, current
versions first and outdated ones labelled. It adds nothing when nothing
clears `recall_min_relevance` (0.35 meaning similarity), never repeats a
memory within a Claude session, skips short messages and slash commands,
never shows wings in `recall_exclude_wings` (default: `library`), and any
error simply adds nothing. About a second per message once warm. Each run is
logged to `~/.engram/recall.log` (counts and timing, not your text) so you
can judge whether it helps. Turn it off with `"recall": false`.

**Easier hook setup.** `engram install-hooks --apply` adds the auto-recall,
auto-save and pre-compact hooks to `~/.claude/settings.json` itself, keeping
your other settings and a `.bak` copy; running it again changes nothing.
`--no-recall` leaves auto-recall out. The recall hook runs with the same
Python that has Engram, so PATH differences can't break it. New:
`engram recall "message"` previews what Claude would be given, and an
`engram-recall` console script.

## 1.6.0

Memories can now be corrected, and Engram keeps track of which version is
current. The model stays the same: Engram does not decide on its own that one
note contradicts another. The agent or person using it records that decision,
and Engram keeps the links sound and makes search and history use them.

**Corrections and lineage** (`engram.lineage`).
- `engram correct <id> "new text"` (MCP: `engram_correct`) saves a
  correction in the same wing/room/hall and marks the old memory superseded.
- `engram supersede <old> <new>` (MCP: `engram_supersede`) links two stored
  memories, and `--undo` reverses that.
- `engram_dispute` marks two memories as conflicting, undecided.
- Links live in `<chateau>/lineage.json`. Every memory without a link is
  current, so existing data needs no migration.
- **Search is history-aware.** Each result has a `status` (`current`,
  `superseded` or `disputed`). An outdated memory is still returned, directly
  below its current replacement, with `superseded_by`, `current_id`,
  `replaced_at` and `reason`. If search found only the old memory, its
  replacement is added above it. Without any links, results are unchanged
  apart from `status: "current"`.
- `engram history <id>` (MCP: `engram_history`) shows a memory's status and
  the whole replacement chain, with dates and reasons.
- **Rules that keep history sound.** A memory is replaced by at most one
  other; only a current memory can be a replacement, so there are no cycles.
  Repeating a link or a correction is a no-op. Each change is a single atomic
  file replace under a lock. A correction whose link is refused removes the
  memory it just saved.
- `engram_add_memory` lists `possible_updates`: existing memories in the same
  wing the new one may replace. This is only a hint; nothing is linked until
  the agent says so. It also accepts `supersedes` and `reason`.
- `engram search` shows a short ID column and labels outdated, current and
  disputed memories. Commands accept a unique ID prefix of 4 or more characters.

**Backup and restore** (`engram.backup`).
- `engram export FILE[.gz]` writes every drawer (IDs, timestamps, tags, pinned
  state), wings, rooms, closets, tunnels, the lineage ledger, provenance, the
  knowledge graph, identity, and agent profiles and diaries to one JSON file.
- `engram import FILE` checks the whole file first: format version, names,
  duplicate IDs, clashes with stored memories, and that the merged lineage is
  sound. If anything fails, nothing is written. It then restores and rebuilds
  the search indexes.
- Re-importing is safe: identical items are skipped. `--dry-run` reports
  without writing; `--overwrite` replaces memories whose content differs.
- The format is documented in `docs/backup-format.md`.

**Compatibility.**
- Existing search, save and Python API calls behave as before, and the MCP
  server keeps its 22 tools (now 26).
- `Drawer.from_dict` ignores fields it doesn't know, so drawers written by a
  newer Engram still load.
- The `provenance/` folder is no longer listed as a wing.

## 1.5.2

**`engram-mcp` command.** Installing Engram now also installs `engram-mcp`,
which starts the MCP server. Connecting Claude Code is one line that works
however Engram was installed (pip, pipx or uv tool):
`claude mcp add engram -- engram-mcp`. `python -m engram.mcp_server` still
works.

**README rewritten** for people trying Engram for the first time: what
problem it solves, a real before-and-after example, a two-minute install, and
the benchmarks in plain terms. It now says up front that the embedding model
(about 80 MB) downloads on first use.

## 1.5.1

**Keyword index on by default.** `keyword_search` now defaults to `true`.
Measured on LongMemEval with the 1.5.0 code (`--hybrid --temporal
--preferences --keywords`): R@5 0.988 (1.4.0 default: 0.982), R@10 0.998,
R@1 0.900, with no question type worse. That matches the 1.4.0 default plus
the local reranker on R@5, without the reranker. On LoCoMo it gives R@10
0.921 and R@5 0.849. The index is built from your existing memories the
first time Engram starts after upgrading. Set `"keyword_search": false` in
`~/.engram/config.json` to turn it off. Code that builds its own backend with
`get_backend()` (rather than `backend_from_config()`) is unchanged.

## 1.5.0

Ideas adapted from [Hindsight](https://github.com/vectorize-io/hindsight),
kept local and LLM-free.

**Dates in questions.** "What happened in June?", "on May 8", "8 May 2023",
"in 2022" now steer the time boost the way "two weeks ago" already did
(`engram.temporal`). On by default as part of `temporal_weight`. LoCoMo R@10
rises from 0.874 to 0.901 with no other change.

**Keyword index (opt-in).** `"keyword_search": true` adds a full-text index
(SQLite FTS5 with BM25, part of Python; no download) next to the vector
index, kept in sync on every write and built from existing memories on first
use. Search runs both and merges them with reciprocal rank fusion. LoCoMo
R@10 0.921 and R@5 0.849 (MemPalace hybrid v5: 0.889 / 0.837). Off until it
is measured on LongMemEval too. Both benchmark runners gained `--keywords`.

**Secret redaction (opt-in).** `"redact_secrets": true` replaces API keys,
tokens, private keys and `password=`-style values with `[REDACTED:<kind>]`
before a drawer is saved or indexed (`engram.redact`).

Internals: `backend_from_config()` builds the CLI/MCP/watcher backend in one
place; the MCP server, file miner and plugin import now index the saved
drawer text.

## 1.4.0

**98.8% R@5 on LongMemEval and 88.7% R@10 on LoCoMo with the optional local
reranker, no LLM and no API** (out of the box: 98.2% and 87.4%).
`engram setup-reranker` downloads the model once and turns it on;
`engram setup-reranker --disable` turns it off. It stays off by default, so
existing installs and apps behave exactly as before.

**Optional local reranker** (`engram.reranker`, off by default). A small
cross-encoder (ms-marco-MiniLM-L-6-v2, ONNX) re-reads the top results next to
the query and reorders them. It runs on onnxruntime and tokenizers, which
ChromaDB already installs: no PyTorch, no API key, nothing leaves the machine.
Turn it on with `"reranker": true` or `engram search --rerank`; the model
(~90 MB) is downloaded once to `~/.engram/models/` on first use, and never
while the reranker is off. If it cannot be loaded, search continues without
it. Both benchmark runners gained `--rerank`. On LoCoMo it raises R@10 from
0.874 to 0.887 and R@5 from 0.783 to 0.828 (MemPalace hybrid v5: 0.889 /
0.837). Off by default.

**API contract tests** (`tests/test_public_api.py`) pin the Python calls apps
such as the Amy companion build on.

**LoCoMo benchmark.** `benchmarks/locomo_bench.py` replaces the old stub:
session recall@k over all 1,986 LoCoMo questions, computed the same way as
MemPalace's runner. Engram scores R@10 0.874 with its defaults (0.844 with
semantic search alone, against MemPalace's 0.603 raw and 0.889 hybrid v5).

## 1.3.0

**98.2% R@5 on LongMemEval (R@10 99.2%), with no AI model.** Two new search
signals, both on by default, raised the score from 97.4%:

- **Temporal boosting** (`temporal_weight`, default 0.4): when a query names
  a time ("two weeks ago", "last month", "yesterday"), memories dated near it
  get a boost (`engram.temporal`).
- **Preference summaries** (`preference_summaries`, default on): user
  messages that mention a preference, habit, concern or plan ("I prefer…",
  "I've been struggling with…", "I'm thinking about…") get a short "User has
  mentioned: …" summary indexed alongside them, so a later question on that
  topic finds the message. The stored drawer is unchanged
  (`engram.preferences`). Applies to conversations mined from now on;
  re-mine older ones to add summaries.

The benchmark runner gained `--temporal` and `--preferences`, and messages
now carry their session's date. 1.3.0 also contains everything listed under
1.2.0, which was never published to PyPI.

## 1.2.0

**Installs on any Python 3.9+.** ChromaDB depends on onnxruntime, which has no
build for Python 3.15 yet, so `pip install engram-chateau` failed there with a
`ResolutionImpossible` error (pip backtracked into old ChromaDB releases).
ChromaDB is now skipped on Python 3.15+, and Engram falls back to its built-in
sqlitevec backend with a one-line notice when ChromaDB is not installed. On
Python 3.9–3.14 nothing changes. The ChromaDB requirement now starts at 1.0.

**Faster indexing.** The embedding model is loaded once instead of on every
write, and drawers are indexed in batches: about 5.5× faster mining
(292 → 53 ms per message).

**Hybrid search, on by default.** Search results that share the query's
keywords get a boost (`hybrid_weight` 0.3). On LongMemEval it raised R@5 from
0.968 to 0.974 and made no question type worse. Turn it off with
`engram search --no-hybrid` or `"hybrid_weight": 0` in `~/.engram/config.json`.

**LongMemEval results published.** R@5 0.974 and R@10 0.988 on all 500
questions with the default setup (local embeddings, no LLM), against 0.966
for MemPalace's raw mode; see `benchmarks/BENCHMARKS.md`. The runner gained `--hybrid`, `--resume`, and a
fix for long runs that crashed (thread exhaustion) or lost recall (reused
ChromaDB collections).

## 1.1.0

First release on PyPI as `engram-chateau`: verbatim drawers, chunked
indexing, working Claude Code hooks (`engram install-hooks`), safe ES
shorthand, ChromaDB filter fixes, path-traversal protection and the
LongMemEval runner.
