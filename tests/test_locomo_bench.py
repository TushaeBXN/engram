"""LoCoMo runner: evidence parsing, dates and the pipeline on a tiny sample."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "fixtures" / "locomo_sample.json"


def _bench():
    spec = importlib.util.spec_from_file_location("locomo", ROOT / "benchmarks" / "locomo_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evidence_sessions_parsing():
    ev = _bench().evidence_sessions
    assert ev(["D1:3", "D4:7"]) == {"session_1", "session_4"}
    assert ev(["D8:6; D9:17"]) == {"session_8"}   # one leading ID per entry, as the common runners parse it
    assert ev(["D:11:26", "D"]) == set()
    assert ev([]) == set()


def test_locomo_date():
    parse = _bench()._locomo_date
    assert parse("1:56 pm on 8 May, 2023") == datetime(2023, 5, 8, 13, 56, tzinfo=timezone.utc)
    assert parse("not a date") is None


def test_recall_counts_share_of_gold_sessions():
    recall = _bench()._recall
    assert recall(["session_1", "session_2"], {"session_1"}, 10) == 1.0
    assert recall(["session_3"], {"session_1", "session_3"}, 10) == 0.5
    assert recall(["session_2", "session_1"], {"session_1"}, 1) == 0.0
    assert recall([], set(), 10) == 1.0  # no evidence counts as found, as in the common runners


def test_locomo_runner_on_sample(tmp_path):
    out = tmp_path / "locomo.jsonl"
    result = _bench().run_locomo(SAMPLE, backend="sqlitevec", top_k=10, out=out)
    assert result["conversations"] == 1 and result["questions"] == 5
    assert result["recall@10"] == 1.0  # two sessions, top 10 holds both
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert {r["category"] for r in rows} == {"temporal", "open-domain", "single-hop", "adversarial"}
    assert rows[3]["gold"] == ["session_2"]


def test_locomo_runner_top1_and_options():
    result = _bench().run_locomo(SAMPLE, backend="sqlitevec", top_k=1, hybrid_weight=0.3,
                                 temporal_weight=0.4, preferences=True)
    assert result["questions"] == 5 and 0.0 <= result["recall@1"] <= 1.0
    assert result["hybrid_weight"] == 0.3 and result["preferences"] is True


def test_missing_dataset_returns_error(tmp_path):
    assert "error" in _bench().run_locomo(tmp_path / "nope.json")
