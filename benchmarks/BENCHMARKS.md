# Engram Benchmarks

## Target Performance

| Benchmark         | Metric              | Target     | Notes                        |
|-------------------|---------------------|------------|------------------------------|
| LongMemEval       | Single-session QA   | ≥ 0.68 F1  | 500-turn conversations       |
| LongMemEval       | Multi-session QA    | ≥ 0.61 F1  | cross-session retrieval      |
| LoCoMo            | Entity recall       | ≥ 0.72     | 100-turn social dialogues    |
| LoCoMo            | Event recall        | ≥ 0.69     | temporal event tracking      |
| ES compression    | Factual paragraphs  | 8–10×      | measured by char ratio       |
| ES compression    | Code-heavy content  | 4–6×       | function signatures + bodies |
| ES compression    | Mixed content       | ~6×        | weighted average             |
| Cold-start ctx    | L0 + L1 tokens      | ≤ 170      | measured with tiktoken       |
| Search latency    | p99 (ChromaDB)      | < 200ms    | 100k drawer collection       |
| Search latency    | p99 (FAISS)         | < 50ms     | 100k drawer collection       |
| Mine throughput   | Files/sec           | ≥ 50       | average text file size       |

## Running the Benchmarks

```bash
# LongMemEval (requires longmemeval dataset)
python benchmarks/longmemeval_bench.py --data-dir ~/datasets/longmemeval

# LoCoMo (requires locomo dataset)  
python benchmarks/locomo_bench.py --data-dir ~/datasets/locomo

# ES compression ratio
python benchmarks/longmemeval_bench.py --compression-only
```

## Dataset Sources

- **LongMemEval**: https://github.com/xiaowu0162/LongMemEval
- **LoCoMo**: https://github.com/snap-research/locomo
