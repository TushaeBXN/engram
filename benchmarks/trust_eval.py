#!/usr/bin/env python3
"""Does Engram keep memory trustworthy? A reproducible check of four things.

    python benchmarks/trust_eval.py                 # all four, default backend
    python benchmarks/trust_eval.py --backend sqlitevec --only integrity,reliability
    python benchmarks/trust_eval.py --json results.json

1. integrity    A fact changes. Is the current version found first, is the old
                version kept and labelled, does history survive a backup and
                restore, is repeating a correction harmless?  (Compared with the
                same search with the correction history switched off.)
2. efficiency   How many tokens does each way of giving a model its memory use,
                and does what it hands over contain the answer? Also: how often
                does auto-recall say something when nothing relevant exists?
3. reliability  Kill the writer with SIGKILL at random moments, and run writers
                in parallel: are any files left half-written, do the correction
                and evidence ledgers stay valid, is any update lost?
4. compression Engram Shorthand (used for the wake-up note): size saved, and
                whether names, numbers and identifiers survive a round trip.
5. recall       A small synthetic indirect-question check (R@5). This is a smoke
                test only: for real recall numbers use longmemeval_bench.py and
                locomo_bench.py.

Everything is LLM-free and offline (after the embedding model is cached). The
scenarios are written by the project's author, so they can be too friendly:
read the numbers as a regression check, and add your own cases to
SCENARIOS / FACTS below. Each part runs in a throwaway HOME; your memories are
never touched.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# (subject, old fact, new fact, queries). Queries: indirect, current-fact, and old-wording.
SCENARIOS = [
    ("database", "The billing service stores everything in SQLite because it is simple and local.",
     "The billing service moved to PostgreSQL in April because it needs concurrent writers.",
     ["which datastore does the billing service run on", "do we still use SQLite for billing"]),
    ("auth", "We use Passport sessions for login in the web app.",
     "We replaced Passport with Lucia sessions for login after the memory leaks.",
     ["how do users authenticate in the web app", "are we still on Passport"]),
    ("hosting", "The marketing site is hosted on Heroku.",
     "The marketing site moved from Heroku to Cloudflare Pages in June to cut costs.",
     ["where is the marketing site deployed", "is the marketing site still on Heroku"]),
    ("standup", "The team standup is at 9:30 every morning.",
     "The team standup moved to 10:15 every morning after the office move.",
     ["when does the daily team meeting start", "is standup still at 9:30"]),
    ("coffee", "Brian orders a medium latte with oat milk at Blue Door Coffee.",
     "Brian switched to a double espresso at Blue Door Coffee, no more lattes.",
     ["what does Brian drink at the coffee shop", "does Brian still get the oat milk latte"]),
    ("language", "The data pipeline is written in Python 3.9.",
     "The data pipeline now targets Python 3.12 after the upgrade.",
     ["which python version does the pipeline target", "is the pipeline still on python 3.9"]),
    ("manager", "Dana Whitfield is the engineering manager for the platform team.",
     "Priya Raman took over from Dana as engineering manager of the platform team in March.",
     ["who manages the platform engineers", "is Dana still the platform manager"]),
    ("ci", "CI runs on Jenkins with a nightly build.",
     "CI moved to GitHub Actions and builds on every push.",
     ["what runs our continuous integration", "do we still use Jenkins nightly builds"]),
    ("budget", "The research budget for this year is 40 thousand dollars.",
     "The research budget was cut to 25 thousand dollars after the Q3 review.",
     ["how much money is allocated to research this year", "is the research budget still 40 thousand"]),
    ("deploy", "Deploys happen on Fridays after lunch.",
     "Deploys are banned on Fridays now; releases go out Tuesday mornings.",
     ["which day do releases go out", "can we still deploy on Friday afternoons"]),
]

# (fact, indirect question, answer key). Unrelated notes below add noise.
FACTS = [
    ("We chose Fastify over Express for the API because of its schema validation.", "why did we pick our API framework", "fastify"),
    ("The staging database password rotates on the first Monday of each month.", "when do we change the staging credentials", "first monday"),
    ("Kai's birthday is on March 14 and the team usually does a cake.", "when should we plan the cake for Kai", "march 14"),
    ("The onboarding checklist lives in the Notion page called Welcome Aboard.", "where can a new hire find the first-week to-do list", "welcome aboard"),
    ("Our SLA promises a four hour response for severity one incidents.", "how fast must we react to a critical outage", "four hour"),
    ("We rejected the Redis cache idea because the dataset fits in memory already.", "why didn't we add a caching layer", "fits in memory"),
    ("The mobile app's minimum supported iOS version is 15.", "what is the oldest iPhone software we support", "ios version is 15"),
    ("Invoices are sent on the 25th and payment terms are net 30.", "how long do customers have to pay", "net 30"),
    ("The office printer is called Gutenberg and its admin page is on the 3rd floor router.", "what is the printer named", "gutenberg"),
    ("Anika prefers async updates in Slack over meetings on Wednesdays.", "how does Anika like to get status updates", "async updates"),
    ("The retrospective format we settled on is Start, Stop, Continue.", "which format do we use for sprint reviews of what went well", "start, stop, continue"),
    ("Feature flags are managed in LaunchDarkly and cleaned up every quarter.", "which tool toggles unfinished features", "launchdarkly"),
    ("The data retention policy deletes raw logs after 90 days.", "how long do we keep the raw logs", "90 days"),
    ("We pair program on Thursdays for two hours, starting at 2pm.", "when is the regular pairing session", "thursdays"),
    ("Customer interviews showed that export to CSV is the most requested feature.", "what did users ask for most often", "csv"),
    ("The load test topped out at 1,200 requests per second on the small instance.", "what throughput did the stress test reach", "1,200"),
    ("The legal team requires a data processing addendum before any EU pilot.", "what paperwork is needed before a European trial", "data processing addendum"),
    ("Our brand color is a deep teal, hex 0F766E.", "what is the main colour of the logo", "0f766e"),
    ("The quarterly planning offsite is held in Lisbon every October.", "where do we hold the planning retreat", "lisbon"),
    ("Backups run at 3am UTC and are restored in a test environment weekly.", "how often do we verify we can restore from backup", "weekly"),
]
UNRELATED = [
    "how do I bake sourdough bread at home", "what is the capital of Australia",
    "explain how photosynthesis works", "write a haiku about autumn",
    "what's the boiling point of water at altitude", "translate good morning into Spanish",
    "give me a workout plan for beginners", "who won the world cup in 2010",
    "how do vaccines train the immune system", "suggest names for a golden retriever puppy",
    "what is the difference between a virus and a bacterium", "recommend a good science fiction novel",
    "how many ounces are in a pound", "explain the rules of chess to a child",
    "what causes the northern lights", "how do I remove a red wine stain",
    "summarize the plot of Romeo and Juliet", "what is a good way to learn guitar",
    "how long should I boil an egg", "why is the sky blue",
]
NOISE = [
    "Meeting notes: discussed the roadmap for {t}, nothing decided yet, follow up next week.",
    "Reminder to review the pull request for the {t} module before Friday.",
    "Lunch order for the {t} workshop: sandwiches and fruit, vegetarian options included.",
    "Brainstorm about naming the new {t} dashboard; candidates were Compass, Beacon and Atlas.",
    "Travel booking for the {t} conference is pending approval from finance.",
]
TOPICS = ["analytics", "payments", "search", "onboarding", "reporting", "mobile", "admin", "billing", "alerts",
          "inventory", "scheduling", "notifications"]


def est_tokens(text: str) -> int:
    """Tokens in *text*: tiktoken's cl100k_base when installed, else characters / 4."""
    global _ENC
    try:
        _ENC
    except NameError:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC = None
    return len(_ENC.encode(text)) if _ENC else max(1, round(len(text) / 4))


def tokenizer_name() -> str:
    est_tokens("x")
    return "tiktoken cl100k_base" if _ENC else "estimated (characters / 4)"


# ---------------------------------------------------------------------------
# Workers: each runs in a throwaway HOME so engram's paths are fresh
# ---------------------------------------------------------------------------

def _server():
    from engram.mcp_server import EngramMCPServer
    return EngramMCPServer()


def worker_integrity() -> dict:
    from engram.backup import export_backup, import_backup
    from engram.chateau import Chateau

    srv = _server()
    ids = {}
    for subject, old, new, _ in SCENARIOS:
        a = srv.dispatch("engram_add_memory", {"content": old, "wing": "work", "room": subject})
        ids[subject] = (a["id"], srv.dispatch("engram_correct", {"memory_id": a["id"], "content": new,
                                                                 "reason": "changed"})["new"]["id"])
    n_q = cur_first = base_cur_first = old_labelled = old_kept = 0
    for subject, old, new, queries in SCENARIOS:
        old_id, new_id = ids[subject]
        for q in queries:
            n_q += 1
            res = srv.dispatch("engram_search", {"query": q, "n": 5, "wing": "work"})
            top = next((r for r in res), None)
            cur_first += bool(top and top["id"] == new_id and top["status"] == "current")
            raw = srv.backend.search(q, n=10, where={"wing": "work"})
            raw_top = next((h.get("metadata", {}).get("drawer_id", h["id"]) for h in raw), None)
            base_cur_first += raw_top == new_id        # same search with no correction history
            ranks = {r["id"]: r for r in res}
            if old_id in ranks:
                old_labelled += ranks[old_id]["status"] == "superseded" and ranks[old_id].get("current_id") == new_id
                old_kept += 1
    hist_ok = sum(srv.dispatch("engram_history", {"memory_id": ids[s][1]})["history"][0]["old_text"].startswith(o[:40])
                  for s, o, _, _ in SCENARIOS)
    again = srv.dispatch("engram_correct", {"memory_id": ids["auth"][0], "content": SCENARIOS[1][2]})
    idempotent = (not again["created"]) and sum(1 for _ in srv.palace.iter_drawers()) == 2 * len(SCENARIOS)

    with tempfile.TemporaryDirectory() as t:
        export_backup(Path(t) / "b.json", srv.palace)
        fresh = Chateau(chateau_path=Path(t) / "fresh")
        import_backup(Path(t) / "b.json", fresh)
        from engram.lineage import Lineage
        same = all(Lineage(fresh.path).status(o)["current_id"] == n for o, n in ids.values())
        same &= sum(1 for _ in fresh.iter_drawers()) == 2 * len(SCENARIOS)
    return {
        "scenarios": len(SCENARIOS), "queries": n_q,
        "current_first": cur_first / n_q, "current_first_without_history": base_cur_first / n_q,
        "outdated_shown_and_labelled": f"{old_labelled}/{old_kept}",
        "history_readable": f"{hist_ok}/{len(SCENARIOS)}",
        "correction_repeat_is_harmless": idempotent, "backup_restore_keeps_chain": bool(same),
    }


def _corpus(srv):
    """The test facts plus 200 unrelated work notes, saved and indexed in one batch."""
    from engram.chateau import Drawer
    from engram.indexing import index_drawers

    rng = random.Random(7)
    notes = [(f, "notes") for f, _, _ in FACTS]
    notes += [(rng.choice(NOISE).format(t=rng.choice(TOPICS)) + f" (note {i})", "misc") for i in range(200)]
    items = []
    for text, room in notes:
        d = Drawer(content=text, wing="team", room=room, hall="facts")
        srv.palace.save_drawer(d)
        items.append((d.id, d.content, {"wing": "team", "room": room, "hall": "facts",
                                        "timestamp": d.timestamp, "pinned": False}))
    index_drawers(srv.backend, items)


def worker_efficiency() -> dict:
    from engram.recall import recall

    srv = _server()
    _corpus(srv)
    cfg = {**srv.cfg, "recall": True}
    everything = "\n".join(d.text() for d in srv.palace.iter_drawers())
    rows = {"dump_everything": [], "top5_raw": [], "engram_recall": []}
    hit = {k: 0 for k in rows}
    for fact, q, key in FACTS:
        raw = "\n".join(r["text"] for r in srv.searcher.search(q, n=5))
        note = recall(q, searcher=srv.searcher, cfg=cfg, remember=False)
        for name, text in (("dump_everything", everything), ("top5_raw", raw), ("engram_recall", note)):
            rows[name].append(est_tokens(text))
            hit[name] += key in text.lower()
    sweep = []
    for bar in (0.20, 0.25, 0.30, 0.35, 0.40, 0.45):
        c = {**cfg, "recall_min_relevance": bar, "recall_other_min_relevance": max(bar, 0.55)}
        got = sum(key in recall(q, searcher=srv.searcher, cfg=c, remember=False).lower() for _, q, key in FACTS)
        said = sum(recall(q, searcher=srv.searcher, cfg=c, remember=False) != "" for q in UNRELATED)
        mark = "   <- default" if abs(bar - float(cfg.get("recall_min_relevance", 0.30))) < 1e-9 else ""
        sweep.append(f"bar {bar:.2f}: answer present {got}/{len(FACTS)}, spoke on {said}/{len(UNRELATED)} unrelated{mark}")
    silent = sum(recall(q, searcher=srv.searcher, cfg=cfg, remember=False) == "" for q in UNRELATED)
    wake = srv.stack.wake_up(rebuild_l1=True)
    n = len(FACTS)
    return {
        "tokenizer": tokenizer_name(), "memories": 200 + n, "questions": n,
        **{f"{k}_mean_tokens": round(sum(v) / n) for k, v in rows.items()},
        **{f"{k}_answer_present": hit[k] / n for k in rows},
        "unrelated_questions_answered_with_silence": f"{silent}/{len(UNRELATED)}",
        "relevance_bar_sweep": sweep,
        "wake_up_tokens": est_tokens(wake),
    }


def worker_recall() -> dict:
    srv = _server()
    _corpus(srv)
    r5 = r1 = 0
    for fact, q, _ in FACTS:
        top = [r["text"] for r in srv.searcher.search(q, n=5)]
        r5 += fact in top
        r1 += bool(top) and top[0] == fact
    n = len(FACTS)
    return {"questions": n, "memories": 200 + n, "R@1": r1 / n, "R@5": r5 / n}


def worker_compression() -> dict:
    import re

    from engram.shorthand import compress, decompress

    texts = [f for f, _, _ in FACTS] + [o for _, o, _, _ in SCENARIOS] + [n for _, _, n, _ in SCENARIOS]
    key = re.compile(r"\b(?!The\b)[A-Z][\w.-]+\b|\b\d[\d,.:]*\b")      # names, identifiers, numbers, times
    ratios, kept, total, whole = [], 0, 0, 0
    for text in texts:
        back = decompress(compress(text)).lower()
        ratios.append(len(text) / max(1, len(compress(text))))
        keys = {m.strip(".,:").lower() for m in key.findall(text)}
        found = {k for k in keys if k in back}
        kept, total, whole = kept + len(found), total + len(keys), whole + (found == keys)
    return {"texts": len(texts), "mean_size_ratio": round(sum(ratios) / len(ratios), 2),
            "names_numbers_and_ids_kept": f"{kept}/{total}", "texts_with_every_one_kept": f"{whole}/{len(texts)}",
            "note": "short single sentences; articles ('the') are the one thing it drops by design"}


def _writer(home: str, seed: int, big: bool) -> None:
    """Child process: save memories and corrections as fast as possible until killed."""
    os.environ["HOME"] = home
    sys.path.insert(0, str(ROOT))
    import engram.chateau as chateau_module
    from engram.chateau import Chateau, Drawer
    from engram.lineage import Lineage
    from engram.relations import Relations

    if os.environ.get("ENGRAM_EVAL_LEGACY_WRITES"):
        chateau_module.atomic_write_text = lambda path, text: Path(path).write_text(text)
    palace = Chateau(chateau_path=Path(home) / "chateau")
    lin, rel = Lineage(palace.path), Relations(palace.path)
    pad = ("lorem ipsum " * 20000) if big else ""
    i = 0
    while True:
        a = Drawer(content=f"fact {seed}-{i} {pad}", wing="w", room="r", hall="facts")
        b = Drawer(content=f"fact {seed}-{i} revised {pad}", wing="w", room="r", hall="facts")
        palace.save_drawer(a)
        palace.save_drawer(b)
        lin.supersede(a.id, b.id, reason="revised")
        rel.add("based_on", b.id, a.id)
        i += 1


def worker_reliability(trials: int = 40) -> dict:
    sys.path.insert(0, str(ROOT))
    from engram.chateau import Chateau
    from engram.lineage import Lineage, validate_links
    from engram.relations import Relations, validate_relations

    rng = random.Random(11)
    damaged = leftovers = ledger_bad = drawers_seen = 0
    for trial in range(trials):
        home = tempfile.mkdtemp()
        p = subprocess.Popen([sys.executable, __file__, "--writer", home, str(trial), "big"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(rng.uniform(0.4, 1.2))
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        palace = Chateau(chateau_path=Path(home) / "chateau")
        bad = palace.unreadable_files()
        damaged += sum(1 for f in bad if f.suffix == ".json")
        leftovers += sum(1 for f in bad if f.suffix == ".tmp")
        drawers_seen += sum(1 for _ in palace.iter_drawers())
        try:
            validate_links(Lineage(palace.path).links())
            validate_relations(Relations(palace.path).links())
        except Exception:
            ledger_bad += 1
    # parallel writers: nothing lost, ledgers valid
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    from engram.chateau import Drawer
    palace = Chateau(chateau_path=Path(home) / "chateau")
    pairs = []
    for i in range(120):
        a, b = Drawer(content=f"a{i}", wing="w", room="r", hall="facts"), Drawer(content=f"b{i}", wing="w", room="r", hall="facts")
        palace.save_drawer(a)
        palace.save_drawer(b)
        pairs.append((a.id, b.id))
    code = (f"import sys,json;sys.path.insert(0,{repr(str(ROOT))});from engram.chateau import Chateau;"
            "from engram.lineage import Lineage;from engram.relations import Relations;"
            f"from pathlib import Path;p=Chateau(chateau_path=Path({repr(home)})/'chateau');"
            "l,r=Lineage(p.path),Relations(p.path);"
            "[(l.supersede(a,b),r.add('based_on',b,a)) for a,b in json.loads(sys.argv[1])]")
    procs = [subprocess.Popen([sys.executable, "-c", code, json.dumps(pairs[k::6])]) for k in range(6)]
    for q in procs:
        q.wait()
    lost = 120 - len(Lineage(palace.path).links())
    lost_rel = 120 - len(Relations(palace.path).links())
    return {
        "kill_trials": trials, "memories_on_disk_after_kills": drawers_seen,
        "half_written_memory_files": damaged, "interrupted_write_leftovers": leftovers,
        "trials_with_invalid_ledger": ledger_bad,
        "parallel_writers": 6, "updates_lost_correction_ledger": lost, "updates_lost_evidence_ledger": lost_rel,
    }


WORKERS = {"integrity": worker_integrity, "efficiency": worker_efficiency,
           "reliability": worker_reliability, "recall": worker_recall, "compression": worker_compression}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_part(name: str, backend: str, legacy_writes: bool) -> dict:
    home = tempfile.mkdtemp(prefix="engram-eval-")
    # Share the downloaded embedding model instead of fetching it again for every part.
    real = Path(os.environ.get("EVAL_REAL_HOME") or Path.home()) / ".cache" / "chroma"
    real.mkdir(parents=True, exist_ok=True)
    (Path(home) / ".cache").mkdir()
    (Path(home) / ".cache" / "chroma").symlink_to(real)
    env = {**os.environ, "HOME": home, "ENGRAM_VECTOR_BACKEND": backend, "PYTHONPATH": str(ROOT)}
    if legacy_writes:
        env["ENGRAM_EVAL_LEGACY_WRITES"] = "1"
    out = subprocess.run([sys.executable, __file__, "--worker", name], env=env, capture_output=True, text=True)
    if out.returncode:
        return {"error": (out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "failed"}
    return json.loads(out.stdout.strip().splitlines()[-1])


def pct(x) -> str:
    return f"{x * 100:.0f}%" if isinstance(x, float) else str(x)


def report(results: dict, backend: str) -> str:
    lines = [f"Engram trust evaluation  (backend: {backend})", ""]
    for part, data in results.items():
        lines.append(part.upper())
        for k, v in data.items():
            if isinstance(v, list):
                lines.append(f"  {k.replace('_', ' ')}")
                lines.extend(f"      {item}" for item in v)
            else:
                lines.append(f"  {k.replace('_', ' '):<44} {pct(v) if isinstance(v, float) and v <= 1 else v}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="chromadb", choices=["chromadb", "sqlitevec"])
    ap.add_argument("--only", default="integrity,efficiency,reliability,compression,recall")
    ap.add_argument("--json", help="also write the results here")
    ap.add_argument("--legacy-writes", action="store_true", help="reliability: use pre-1.10.1 plain file writes")
    ap.add_argument("--worker")
    ap.add_argument("--writer", nargs=3, metavar=("HOME", "SEED", "BIG"))
    args = ap.parse_args()
    if args.writer:
        _writer(args.writer[0], int(args.writer[1]), args.writer[2] == "big")
        return
    if args.worker:
        if os.environ.get("ENGRAM_EVAL_LEGACY_WRITES"):
            import engram.chateau as c
            c.atomic_write_text = lambda path, text: Path(path).write_text(text)
        print(json.dumps(WORKERS[args.worker]()))
        return
    results = {name: run_part(name, args.backend, args.legacy_writes) for name in args.only.split(",")}
    print(report(results, args.backend))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
