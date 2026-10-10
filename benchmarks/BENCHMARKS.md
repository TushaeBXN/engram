# Engram Benchmarks

## Target Performance

These are goals. ES compression measures about 1.6× on factual text and 1.1× on code. The LongMemEval runner is implemented (below); its full 500-question score has not been published yet. The LoCoMo runner is still a stub that returns `"status": "stub"`.

| Benchmark         | Metric              | Target     | Notes                        |
|-------------------|---------------------|------------|------------------------------|
| LongMemEval       | Session recall R@5  | ≥ 0.95     | 500 questions, longmemeval_s |
| LongMemEval       | Session recall R@10 | ≥ 0.97     | same run                     |
| LoCoMo            | Entity recall       | ≥ 0.72     | 100-turn social dialogues    |
| LoCoMo            | Event recall        | ≥ 0.69     | temporal event tracking      |
| ES compression    | Factual paragraphs  | ≥ 1.5×     | measured by char ratio       |
| ES compression    | Code-heavy content  | ≥ 1.1×     | function signatures + bodies |
| ES compression    | Mixed content       | ≥ 1.4×     | weighted average             |
| Cold-start ctx    | L0 + L1 tokens      | ≤ 170      | measured with tiktoken       |
| Search latency    | p99 (ChromaDB)      | < 200ms    | 100k drawer collection       |
| Search latency    | p99 (FAISS)         | < 50ms     | 100k drawer collection       |
| Mine throughput   | Files/sec           | ≥ 50       | average text file size       |

## LongMemEval: how it is measured

For each of the 500 questions in `longmemeval_s_cleaned.json`, the runner builds a
fresh château from that question's haystack sessions **using Engram's normal
pipeline**: every message goes through `ConvoMiner` (verbatim drawer, chunked
index), one room per session, and the question is answered with `Searcher`, as
`engram search` would. Ranked drawers are mapped back to their session.

A question counts as a hit at *k* if any gold answer session is in the top *k*
(`recall_any@k`, the same "R@k" MemPalace reports for its raw mode). The runner
also reports `recall_all@5`, `ndcg_any@10`, a per-question-type breakdown, and
can write every question's ranking to JSONL with `--out`.

Differences from MemPalace's raw mode, so numbers are compared fairly: Engram
indexes both user and assistant messages by default (`--roles user` matches
MemPalace), stores one drawer per message rather than one document per session,
and splits long messages into ~900-character chunks.

```bash
mkdir -p ~/datasets/longmemeval
curl -fsSL -o ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --out lme_results.jsonl                # full run, ChromaDB + all-MiniLM-L6-v2
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --limit 20                             # quick smoke test
```

`tests/fixtures/longmemeval_sample.json` is a four-question hand-written sample
used to test the runner; its scores are not benchmark results.

## Running the Benchmarks

```bash
# LongMemEval (requires longmemeval dataset, see above)
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json

# LoCoMo (requires locomo dataset)  
python benchmarks/locomo_bench.py --data-dir ~/datasets/locomo

# ES compression ratio
python benchmarks/longmemeval_bench.py --compression-only
```

## Dataset Sources

- **LongMemEval**: https://github.com/xiaowu0162/LongMemEval (cleaned data: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- **LoCoMo**: https://github.com/snap-research/locomo
