# Changelog

## Unreleased

**Temporal and preference boosting (opt-in, being measured).**
- `temporal_weight` (config, default 0): when a query names a time ("two
  weeks ago", "last month", "yesterday"), memories dated near it get a boost
  (`engram.temporal`).
- `preference_summaries` (config, default off): user messages that mention a
  preference, habit, concern or plan ("I prefer…", "I've been struggling
  with…", "I'm thinking about…") get a short "User has mentioned: …" summary
  indexed alongside them, so a later question about that topic finds the
  message. The stored drawer is unchanged (`engram.preferences`).

Both become defaults only if they raise the LongMemEval score; the runner
gained `--temporal` and `--preferences`, and messages now carry their
session's date.

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
