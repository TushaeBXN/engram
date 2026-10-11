# Changelog

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

**Hybrid search (opt-in).** `engram search --hybrid`, or `"hybrid_weight": 0.3`
in `~/.engram/config.json` for the CLI and MCP server, boosts results that
share the query's keywords. Off by default.

**LongMemEval results published.** R@5 0.968 and R@10 0.986 on all 500
questions with the default setup (local embeddings, no LLM); see
`benchmarks/BENCHMARKS.md`. The runner gained `--hybrid`, `--resume`, and a
fix for long runs that crashed (thread exhaustion) or lost recall (reused
ChromaDB collections).

## 1.1.0

First release on PyPI as `engram-chateau`: verbatim drawers, chunked
indexing, working Claude Code hooks (`engram install-hooks`), safe ES
shorthand, ChromaDB filter fixes, path-traversal protection and the
LongMemEval runner.
