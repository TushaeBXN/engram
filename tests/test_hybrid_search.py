"""Hybrid search: keyword overlap boosts semantic scores, off by default."""

import importlib.util
from pathlib import Path

from typer.testing import CliRunner

from engram.chateau import Chateau
from engram.cli import app
from engram.searcher import Searcher, keyword_overlap, keywords

ROOT = Path(__file__).resolve().parent.parent


class FixedBackend:
    """Returns canned hits so the ranking change comes only from the boost."""

    def __init__(self, hits):
        self.hits = hits

    def search(self, query, n=10, where=None):
        return [dict(h, metadata=dict(h.get("metadata", {}))) for h in self.hits][:n]


HITS = [
    {"id": "vague", "text": "We talked about getting a new vehicle at some point.", "score": 0.60},
    {"id": "exact", "text": "My new car is a blue Subaru Outback from 2023.", "score": 0.55},
]


def searcher(tmp_path, hits=HITS, config=None):
    return Searcher(FixedBackend(hits), Chateau(chateau_path=tmp_path / "c"), config or {})


def test_keywords_drop_stopwords_and_normalise_forms():
    assert keywords("What did I say about the Subaru I bought in 2023?") == {"subaru", "bought", "2023"}
    assert keywords("tomatoes") == keywords("tomato")
    assert keywords("planned running studied") == keywords("plan run study")
    assert keywords("v2 is ok") == {"v2"}


def test_keyword_overlap_fraction():
    q = keywords("blue Subaru Outback")
    assert keyword_overlap(q, "a blue Subaru Outback") == 1.0
    assert keyword_overlap(q, "a red Subaru") == 1 / 3
    assert keyword_overlap(set(), "anything") == 0.0


def test_hybrid_is_off_by_default(tmp_path):
    hits = searcher(tmp_path).search("which Subaru Outback did I buy", no_decay=True)
    assert [h["id"] for h in hits] == ["vague", "exact"]
    assert all(h["keyword_overlap"] == 0.0 for h in hits)
    assert hits[0]["final_score"] == hits[0]["semantic_score"]


def test_hybrid_weight_reranks_by_keywords(tmp_path):
    hits = searcher(tmp_path).search("which Subaru Outback did I buy", no_decay=True,
                                     hybrid_weight=0.3)
    assert [h["id"] for h in hits] == ["exact", "vague"]
    exact = hits[0]
    assert exact["keyword_overlap"] > 0
    assert exact["final_score"] == round(0.55 * (1 + 0.3 * exact["keyword_overlap"]), 4)


def test_hybrid_weight_from_config(tmp_path):
    hits = searcher(tmp_path, config={"hybrid_weight": 0.3}).search(
        "which Subaru Outback did I buy", no_decay=True)
    assert hits[0]["id"] == "exact"
    # An explicit 0 overrides the config
    hits = searcher(tmp_path, config={"hybrid_weight": 0.3}).search(
        "which Subaru Outback did I buy", no_decay=True, hybrid_weight=0)
    assert hits[0]["id"] == "vague"


def test_hybrid_never_lifts_negative_scores(tmp_path):
    hits = [{"id": "neg", "text": "Subaru Outback", "score": -0.2}]
    out = searcher(tmp_path, hits).search("Subaru Outback", no_decay=True, hybrid_weight=0.3)
    assert out[0]["final_score"] == -0.2


def test_cli_search_hybrid_flag(engram_home, tmp_path, monkeypatch):
    import engram.cli as cli
    s = searcher(tmp_path)
    calls = []
    real = s.search
    monkeypatch.setattr(s, "search", lambda *a, **k: (calls.append(k), real(*a, **k))[1])
    monkeypatch.setattr(cli, "_searcher", lambda *a, **k: s)
    runner = CliRunner()
    assert runner.invoke(app, ["search", "Subaru Outback"]).exit_code == 0
    result = runner.invoke(app, ["search", "Subaru Outback", "--hybrid", "--hybrid-weight", "0.5"])
    assert result.exit_code == 0, result.output
    assert [c["hybrid_weight"] for c in calls] == [None, 0.5]


def test_longmemeval_runner_hybrid_on_sample():
    spec = importlib.util.spec_from_file_location("lme", ROOT / "benchmarks" / "longmemeval_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.run_longmemeval(ROOT / "tests" / "fixtures" / "longmemeval_sample.json",
                                 backend="sqlitevec", hybrid_weight=0.3)
    assert result["questions"] == 4 and result["hybrid_weight"] == 0.3
    assert result["recall_any@5"] == 1.0
