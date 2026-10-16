# Changelog

## Unreleased

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
