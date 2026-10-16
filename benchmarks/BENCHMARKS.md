# Engram Benchmarks

## Target Performance

These are goals; measured results are in the next section.

| Benchmark         | Metric              | Target     | Notes                        |
|-------------------|---------------------|------------|------------------------------|
| LongMemEval       | Session recall R@5  | ≥ 0.95     | 500 questions, longmemeval_s |
| LongMemEval       | Session recall R@10 | ≥ 0.97     | same run                     |
| LoCoMo            | Session recall R@10 | ≥ 0.85     | 1,986 questions, locomo10    |
| LoCoMo            | Session recall R@5  | ≥ 0.75     | same run                     |
| ES compression    | Factual paragraphs  | ≥ 1.5×     | measured by char ratio       |
| ES compression    | Code-heavy content  | ≥ 1.1×     | function signatures + bodies |
| ES compression    | Mixed content       | ≥ 1.4×     | weighted average             |
| Cold-start ctx    | L0 + L1 tokens      | ≤ 170      | measured with tiktoken       |
| Search latency    | p99 (ChromaDB)      | < 200ms    | 100k drawer collection       |
| Search latency    | p99 (FAISS)         | < 50ms     | 100k drawer collection       |
| Mine throughput   | Files/sec           | ≥ 50       | average text file size       |

## Measured results

### LongMemEval (longmemeval_s, 500 questions)

Engram 1.3.0, ChromaDB with all-MiniLM-L6-v2, user and assistant messages
indexed, no reranker, no LLM. Run on an Apple-silicon Mac mini at about 13 s
per question (each question builds its own index). Three configurations:

- **Semantic**: the embedding score alone (runner default).
- **Hybrid (keywords)**: plus the keyword boost (`--hybrid`).
- **1.3/1.4 default**: plus temporal boosting and preference summaries
  (`--hybrid --temporal --preferences`), which is what Engram 1.3.0 and 1.4.0 do.
- **1.5 default**: the same flags plus `--keywords`, run with Engram 1.5.0
  code, which also understands absolute dates in questions. This is what
  Engram does by default from 1.5.1.

| Metric        | Semantic | Hybrid (keywords) | 1.4 default | 1.4 default + local reranker | **1.5 default** |
|---------------|----------|-------------------|-------------|------------------------------|-----------------|
| R@1           | 0.868    | 0.874             | 0.888       | **0.924**                    | 0.900           |
| R@3           | 0.952    | 0.954             | 0.970       | 0.974                        | 0.968           |
| **R@5**       | 0.968    | 0.974             | 0.982       | **0.988**                    | **0.988**       |
| R@10          | 0.986    | 0.988             | 0.992       | 0.990                        | **0.998**       |
| recall_all@5  | 0.854    | 0.874             | 0.882       | **0.902**                    | 0.886           |
| NDCG@10       | 0.905    | 0.914             | 0.923       | **0.940**                    | 0.933           |

By question type (R@5):

| Type                      | n   | Semantic | Hybrid (keywords) | 1.4 default | + reranker | 1.5 default |
|---------------------------|-----|----------|-------------------|-------------|------------|-------------|
| single-session-assistant  | 56  | 1.000    | 1.000             | 1.000       | 1.000      | 1.000       |
| knowledge-update          | 78  | 0.987    | 1.000             | 1.000       | 1.000      | 1.000       |
| multi-session             | 133 | 0.992    | 0.992             | 0.992       | 0.992      | 0.992       |
| single-session-user       | 70  | 0.914    | 0.929             | 0.971       | 0.986      | **1.000**   |
| single-session-preference | 30  | 0.967    | 0.967             | 0.967       | **1.000**  | 0.967       |
| temporal-reasoning        | 133 | 0.947    | 0.955             | 0.962       | 0.970      | 0.970       |

The 1.5 default misses 6 questions at R@5 (1.4: 9) and only one at R@10, with
no question type worse than 1.4. Dates and the keyword index were measured
together here, so their individual shares are not separated on LongMemEval
(on LoCoMo, below, they are). The reranker still puts the right session
first more often (R@1 0.924 vs 0.900); it has not yet been run on top of the
1.5 default.

The reranker column adds `--rerank`: Engram's optional local cross-encoder
(ms-marco-MiniLM-L-6-v2, ONNX, no LLM or API) reordering the top 20 results,
a setting chosen before the run. It is off by default; `engram setup-reranker`
turns it on. R@10 drops by one question because only the top 20 are reordered.

Each step improved some question types and made none worse, which is why all
three signals are on by default. Temporal boosting and preference summaries
were measured together in one run, so their individual shares are not
separated; the temporal weight (0.4) was set before the run, not tuned on it.

For reference, MemPalace reports R@5 0.966 for its raw mode and 0.984 for its
hybrid v4 (keyword, temporal and preference boosting, tuned on 50 questions
and scored on the other 450). The setups differ: Engram indexes assistant messages as well
(which is why it answers every single-session-assistant question), MemPalace's
raw mode indexes user turns only, and one question is worth 0.002.
`--roles user` runs Engram the MemPalace way.

### LoCoMo (locomo10, 10 conversations, 1,986 questions)

ChromaDB with all-MiniLM-L6-v2, no LLM. Run on a Linux CPU machine in about
18 minutes per configuration (the `--rerank` run on an Apple-silicon Mac mini). Each conversation
is mined once (one room per session, one drawer per turn written as
`Speaker said, "…"`) and all of its questions are asked against it. Metric:
for each question, the share of its evidence sessions among the top-k
retrieved sessions, averaged over all questions in all five categories,
exactly as MemPalace's `locomo_bench.py --granularity session` computes it
(including its parsing of the evidence IDs).

| Metric          | Semantic | 1.4.0 default | 1.4.0 + `--rerank` | 1.5.0 default (adds dates) | **1.5.1 default** (+ `--keywords`) |
|-----------------|----------|---------------|--------------------|--------------------------|--------------------|
| **R@10**        | 0.844    | 0.874         | 0.887              | **0.901**                | **0.921**          |
| R@5             | 0.727    | 0.783         | 0.828              | 0.821                    | **0.849**          |
| Perfect (1.0)   | 1,595    | 1,658         | 1,691              | 1,715                    | 1,758              |
| Zero (0.0)      | 231      | 179           | 159                | 127                      | 91                 |

"1.5.0 default" is `--hybrid --temporal --preferences` with the current code, which
also understands absolute dates in questions ("on 8 May 2023", "in June");
252 of the 1,986 questions name one. `--keywords` adds the full-text keyword
index (SQLite FTS5, BM25) merged with the meaning search by reciprocal rank
fusion (k = 60), as Hindsight does. From 1.5.1 the keyword index is on by default, so
the last column is Engram's default search. Neither was tuned on LoCoMo: the date
windows and the fusion constant were set before these runs.

By category (R@10), using MemPalace's category names:

| Category           | n   | Semantic | 1.4.0 default | + rerank | Default | + keywords |
|--------------------|-----|----------|---------------|----------|---------|------------|
| open-domain        | 841 | 0.893    | 0.928         | 0.936    | 0.957   | 0.974      |
| adversarial        | 446 | 0.850    | 0.888         | 0.904    | 0.915   | 0.957      |
| temporal           | 321 | 0.859    | 0.888         | 0.905    | 0.929   | 0.929      |
| single-hop         | 282 | 0.717    | 0.734         | 0.761    | 0.739   | 0.762      |
| temporal-inference | 96  | 0.718    | 0.701         | 0.683    | 0.733   | 0.718      |

The `--rerank` column uses the optional local reranker (ms-marco-MiniLM-L-6-v2,
ONNX, reordering the top 20 results; `rerank_top` was set before the run). It
ran on an Apple-silicon Mac mini in under 5 minutes for all 1,986 questions.
It is off by default in Engram.

The 1.4.0 defaults helped four categories and cost temporal-inference about
1.6 points; with dates understood, every category is above the semantic
baseline.

For reference, MemPalace reports R@10 0.603 for raw session retrieval and
0.889 (R@5 0.837) for its hybrid v5, which adds person-name and
quoted-phrase boosts and a heavier keyword weight. Its raw mode embeds each
whole session as one document, which the embedding model truncates; Engram
indexes every turn, which is where most of its 24-point lead on raw
retrieval comes from.

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
  --hybrid --out lme_hybrid.jsonl        # keyword boost only
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --hybrid --temporal --preferences --out lme_14.jsonl        # 1.4 default search (98.2%)
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json \
  --hybrid --temporal --preferences --keywords --out lme_default.jsonl   # Engram's default search (98.8%)
```

`--hybrid` applies the keyword boost Engram uses by default (`hybrid_weight`
0.3): each hit's score is multiplied by `1 + 0.3 × (share of the question's
keywords found in the hit)`. Change the weight with `--hybrid-weight`.
`--temporal` adds the time boost (`1 + 0.4 × closeness` to a time the question
names, relative to the question's date) and `--preferences` indexes preference
summaries with user messages. All three together reproduce Engram's default;
with none, the runner measures semantic search alone.

`tests/fixtures/longmemeval_sample.json` is a four-question hand-written sample
used to test the runner; its scores are not benchmark results.

## Running the Benchmarks

```bash
# LongMemEval (requires longmemeval dataset, see above)
python benchmarks/longmemeval_bench.py ~/datasets/longmemeval/longmemeval_s_cleaned.json

# LoCoMo (dataset: one JSON file from GitHub)
mkdir -p ~/datasets/locomo
curl -fsSL -o ~/datasets/locomo/locomo10.json \
  https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python benchmarks/locomo_bench.py ~/datasets/locomo/locomo10.json                # semantic
python benchmarks/locomo_bench.py ~/datasets/locomo/locomo10.json \
  --hybrid --temporal --preferences --out locomo_default.jsonl                   # Engram's default
python benchmarks/locomo_bench.py ~/datasets/locomo/locomo10.json \
  --hybrid --temporal --preferences --keywords --out locomo_kw.jsonl             # plus the keyword index
python benchmarks/locomo_bench.py ~/datasets/locomo/locomo10.json \
  --hybrid --temporal --preferences --rerank --out locomo_rerank.jsonl           # plus the local reranker

# ES compression ratio
python benchmarks/longmemeval_bench.py --compression-only
```

## Dataset Sources

- **LongMemEval**: https://github.com/xiaowu0162/LongMemEval (cleaned data: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- **LoCoMo**: https://github.com/snap-research/locomo
