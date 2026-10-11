# Engram Benchmarks

## Target Performance

These are goals; measured results are in the next section. The LoCoMo runner is still a stub that returns `"status": "stub"`.

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

## Measured results

### LongMemEval (longmemeval_s, 500 questions)

Engram 1.2.0, ChromaDB with all-MiniLM-L6-v2, user and assistant messages
indexed, no reranker, no LLM. Run on an Apple-silicon Mac mini at about 13 s
per question (each question builds its own index). "Hybrid" is Engram's
default search (keyword boost, `hybrid_weight` 0.3, `--hybrid` in the runner);
"semantic" is the embedding score alone.

| Metric        | Semantic | Hybrid (default) |
|---------------|----------|------------------|
| R@1           | 0.868    | 0.874            |
| R@3           | 0.952    | 0.954            |
| **R@5**       | 0.968    | **0.974**        |
| R@10          | 0.986    | 0.988            |
| recall_all@5  | 0.854    | 0.874            |
| NDCG@10       | 0.905    | 0.914            |

By question type (R@5):

| Type                      | n   | Semantic | Hybrid |
|---------------------------|-----|----------|--------|
| single-session-assistant  | 56  | 1.000    | 1.000  |
| knowledge-update          | 78  | 0.987    | 1.000  |
| multi-session             | 133 | 0.992    | 0.992  |
| single-session-preference | 30  | 0.967    | 0.967  |
| temporal-reasoning        | 133 | 0.947    | 0.955  |
| single-session-user       | 70  | 0.914    | 0.929  |

The keyword boost improved three question types and made none worse, which
is why it is on by default.

For reference, MemPalace reports R@5 0.966 for its raw mode and 0.984 for its
hybrid v4 (held-out 450 questions; keyword, temporal and preference
boosting). The setups differ: Engram indexes assistant messages as well
(which is why it answers every single-session-assistant question), MemPalace's
raw mode indexes user turns only, and one question is worth 0.002.
`--roles user` runs Engram the MemPalace way.

ES compression: 1.6× factual, 1.1× code, 1.5× mixed.

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
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --hybrid --out lme_hybrid.jsonl        # Engram's default search (keyword boost)
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --hybrid --temporal --preferences --out lme_tp.jsonl   # plus temporal + preference boosting
```

`--hybrid` applies the keyword boost Engram uses by default (`hybrid_weight`
0.3): each hit's score is multiplied by `1 + 0.3 × (share of the question's
keywords found in the hit)`. Change the weight with `--hybrid-weight`. Without
`--hybrid` the runner measures semantic search alone.

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
