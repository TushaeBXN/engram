# Does Engram keep memory trustworthy?

`LongMemEval` and `LoCoMo` ask one question: *does search find the right conversation?*
They say nothing about whether corrections hold, whether a note handed to a model is
small and relevant, or whether a crash can lose a memory. `trust_eval.py` checks those.

```bash
python benchmarks/trust_eval.py                          # everything (about 4 minutes)
python benchmarks/trust_eval.py --only integrity,reliability
python benchmarks/trust_eval.py --backend sqlitevec      # no embedding model needed (weaker search)
python benchmarks/trust_eval.py --json results.json
```

Each part runs in a throwaway home folder, offline and with no LLM, so your own
memories are never touched. **The scenarios are written by the project's author**
(10 changing facts, 20 questions, 200 filler notes), so they can be friendlier than real
life. Treat the numbers as a regression check, and add your own cases to `SCENARIOS` and
`FACTS` at the top of the script.

## Results (Engram 1.10.1)

Linux sandbox, Python 3.11, ChromaDB 1.5.9 with all-MiniLM-L6-v2, default settings.
Tokens are estimated as characters / 4 (`tiktoken` is used when installed).

### 1. Corrections: is the current fact found first, and is history kept?

10 facts that change, 20 questions (a worded-differently question and a "do we still use the
old thing?" question for each).

| | Result |
|---|---|
| Current version is the first result, with correction history | **20 / 20** |
| Same search with no correction history (old and new are equally similar to the question) | 4 / 20 |
| Outdated version still shown, labelled, pointing to the current one | 20 / 20 |
| History readable for every correction | 10 / 10 |
| Repeating a correction saves nothing new | yes |
| Export, then import into an empty memory: same current/outdated chain | yes |

Without the history, the first result was the *outdated* memory in most cases, because an
old fact and its replacement are almost the same text. This is the problem corrections solve.
It is also an easy case for them: it shows the mechanism works, not that it handles every
messy real-life change.

### 2. Context: how much does it hand the model, and does it contain the answer?

220 memories (20 facts, 200 unrelated work notes), 20 indirect questions about the facts,
20 questions about things that are not in memory at all.

| What the model is given | Mean tokens | Contains the answer |
|---|---|---|
| Every memory | 5,134 | 100 % |
| Top 5 search results, full text | 108 | 95 % |
| **Engram auto-recall note** (relevance bar 0.30) | **92** | **85 %** |

- Auto-recall is **56× smaller than pasting everything** and only slightly smaller than a plain
  top-5 (about 15 %). It does **not** beat top-5 on answers: it misses 10 points more, because
  it holds back anything below its relevance bar.
- What the bar buys is silence: on the 20 questions about things not in memory, auto-recall
  said nothing for **20 / 20**. A raw top-5 always returns five results.
- The bar is a trade-off you can move (`recall_min_relevance`):

  | Bar | Questions answered (of 20) | Spoke on unrelated (of 20) |
  |---|---|---|
  | 0.20 | 18 | 5 |
  | 0.25 | 18 | 1 |
  | **0.30 (default)** | 17 | 0 |
  | 0.35 (the default before 1.10.1) | 15 | 0 |
  | 0.40 | 12 | 0 |
  | 0.45 | 11 | 0 |

  The default moved from 0.35 to 0.30 because of this table. It was set from these 20 questions,
  so check it against yours.
- The wake-up note (identity + key facts) measured **124 tokens**. Before 1.10.1 it was **459**
  on the same memories: the "~170 tokens" claim was not enforced, and the facts were picked in
  folder order rather than by importance. Key facts are now pinned first, then newest, skipping
  corrected ones, within `l1_budget_tokens` (default 120).

### 2b. Preferences: found when the question uses different words

6 saved preferences (a favorite bakery, a coffee order, seat choice, diet, a running
habit, editor settings), 9 questions that should bring one up, and 12 that shouldn't.

| Bar | Preference found | False alarms (of 12) |
|---|---|---|
| Same as facts (0.30; before 1.10.3) | 2 / 9 | 1 |
| **Preference bar 0.20 (default)** | **6 / 9** | **1** |

The one false alarm either way is "where should I park downtown tomorrow?". The 3 still
missed need reasoning, not wording ("we're taking clients to dinner" -> "vegetarian").
A live test of the companion app found this: "I'm picking up pastries before work tomorrow"
scores 0.205 against "favorite bakery … lemon scone", under the 0.30 bar. The cases were
chosen while looking at that failure, so treat 6 / 9 as optimistic.

### 3. Reliability: kill the writer, run writers in parallel

Writers save 240 KB memories, corrections and evidence links in a loop; each trial is
killed with SIGKILL at a random moment (40 trials, about 4,400 memories on disk afterwards).

| | Plain file writes (before 1.10.1) | Atomic writes (now) |
|---|---|---|
| Half-written memory files | **10** | **0** |
| Leftover temporary files from an interrupted write | 0 | 22 (harmless; `engram audit --fix` removes old ones) |
| Trials where the correction or evidence ledger was invalid | 0 | 0 |

Before 1.10.1 a memory file cut off by a crash was skipped silently when reading, so the
memory just disappeared. Now writes go to a temporary file and are renamed into place, and
`engram audit` reports any unreadable memory file. The test uses large memories to make the
failure window easy to hit; small memories have a much smaller window, so real-life odds are
far lower than 10 in 40.

Six processes added 120 corrections and 120 evidence links at the same time: **0 lost**,
both ledgers valid.

What is *not* covered: a crash between saving a memory and indexing it leaves a memory on
disk that search can't find until `engram reindex`; power loss on a filesystem that doesn't
honour `fsync`; disk corruption.

### 4. Compression (Engram Shorthand, used for the wake-up note)

Short single sentences: mean size ratio **1.15×**, and all 85 names, numbers and identifiers
in the 40 test sentences survived a compress / expand round trip. The only thing it drops by
design is articles ("the"). On longer prose `longmemeval_bench.py --compression-only` reports
factual 1.6×, mixed 1.5×, code 1.1×, on sample text written for that script. Compression
saves a little and loses no facts here, but it is not a large saving: the wake-up budget does
more of the work.

### 5. Recall (smoke test only)

20 indirect questions over the same 220 memories: R@1 **90 %**, R@5 **95 %**. This is too
small and too friendly to compare with anything; for real recall numbers use
`longmemeval_bench.py` and `locomo_bench.py` (see `BENCHMARKS.md`, including the note that
those scores are not held-out).

## What has not been shown

- That any of this makes an AI **more accurate end to end**. These checks measure what
  Engram hands over and keeps, not what a model then does with it. That needs a task benchmark
  with a model in the loop (planned, not built).
- Anything about **speed at scale**: no latency or throughput figures at 100,000 memories have
  been measured, so none are claimed.
- Comparisons with other memory systems on these four measures. Others can run the same
  scenarios against their own system; the cases are in `trust_eval.py`.
