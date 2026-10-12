"""Local reranker (engram.reranker): off by default, never touches the network
unless enabled, and reorders the top results when it is on.

The ONNX path runs against tests/fixtures/tiny_reranker, a sub-1 KB model with
the same inputs and output as ms-marco-MiniLM (score = passage tokens that also
appear in the query), so no 90 MB download is needed.
"""

import importlib.util
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engram import reranker as rr
from engram.chateau import Chateau
from engram.cli import app
from engram.config import DEFAULT_CONFIG
from engram.searcher import Searcher

pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")

ROOT = Path(__file__).resolve().parent.parent
TINY = ROOT / "tests" / "fixtures" / "tiny_reranker"


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(rr, "_LOADED", {})
    monkeypatch.setattr(rr, "_WARNED", set())


class FixedBackend:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, n=10, where=None):
        return [dict(h, metadata=dict(h.get("metadata", {}))) for h in self.hits][:n]


HITS = [  # semantic order: tea, car, jazz
    {"id": "tea", "text": "Tea in the garden", "score": 0.70},
    {"id": "car", "text": "The blue car", "score": 0.65},
    {"id": "jazz", "text": "Brian likes jazz music in the evening", "score": 0.60},
]
QUERY = "what music does Brian like"


def searcher(tmp_path, **cfg):
    config = {"hybrid_weight": 0.0, "decay_factor": 0.0, **cfg}
    return Searcher(FixedBackend(HITS), Chateau(chateau_path=tmp_path / "c"), config)


def test_cross_encoder_scores_pairs():
    ce = rr.CrossEncoder(TINY)
    assert ce.score(QUERY, ["Brian likes jazz music", "The blue car", ""]) == [2.0, 0.0, 0.0]
    assert ce.score(QUERY, []) == []


def test_rerank_reorders_head_and_keeps_tail():
    results = [{"id": i, "text": t} for i, t in [("a", "blue car"), ("b", "brian music"), ("c", "tea")]]
    out = rr.rerank(QUERY, results, rr.CrossEncoder(TINY), top=2)
    assert [h["id"] for h in out] == ["b", "a", "c"]
    assert out[0]["rerank_score"] == 2.0 and "rerank_score" not in out[2]


def test_reranker_is_off_by_default_and_never_loaded(tmp_path, monkeypatch):
    assert DEFAULT_CONFIG["reranker"] is False
    monkeypatch.setattr(rr, "get_reranker", lambda cfg: pytest.fail("reranker must not load"))
    hits = searcher(tmp_path).search(QUERY, no_decay=True)
    assert [h["id"] for h in hits] == ["tea", "car", "jazz"]
    assert all("rerank_score" not in h for h in hits)


def test_reranker_reorders_search_results(tmp_path):
    hits = searcher(tmp_path, reranker=True, reranker_path=str(TINY)).search(QUERY, no_decay=True)
    assert [h["id"] for h in hits] == ["jazz", "tea", "car"]
    assert hits[0]["rerank_score"] == 2.0
    # The argument wins over the config, both ways
    s = searcher(tmp_path, reranker_path=str(TINY))
    assert s.search(QUERY, no_decay=True, rerank=True)[0]["id"] == "jazz"
    s = searcher(tmp_path, reranker=True, reranker_path=str(TINY))
    assert s.search(QUERY, no_decay=True, rerank=False)[0]["id"] == "tea"


def test_rerank_top_limits_the_reordered_results(tmp_path):
    hits = searcher(tmp_path, reranker=True, reranker_path=str(TINY), rerank_top=2).search(
        QUERY, no_decay=True)
    assert [h["id"] for h in hits] == ["tea", "car", "jazz"]  # jazz was outside the top 2


def test_unavailable_model_falls_back_with_one_warning(tmp_path, capsys):
    s = searcher(tmp_path, reranker=True, reranker_path=str(tmp_path / "missing"))
    for _ in range(2):
        assert [h["id"] for h in s.search(QUERY, no_decay=True)] == ["tea", "car", "jazz"]
    assert capsys.readouterr().err.count("reranker unavailable") == 1


def test_ensure_model_without_download_raises(tmp_path):
    with pytest.raises(rr.RerankerUnavailable):
        rr.ensure_model(base=tmp_path, download=False)


def test_ensure_model_downloads_once(tmp_path, monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, url):
            calls.append(url)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"data"

    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(url))
    target = rr.ensure_model(base=tmp_path)
    assert sorted(p.name for p in target.iterdir()) == ["model.onnx", "tokenizer.json"]
    assert calls == [rr.DOWNLOAD_URL.format(model=rr.DEFAULT_MODEL, path=p) for _, p in rr.MODEL_FILES]
    rr.ensure_model(base=tmp_path)  # already there: no second download
    assert len(calls) == 2


def test_failed_download_leaves_no_partial_files(tmp_path, monkeypatch):
    import requests

    def boom(url, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(rr.RerankerUnavailable):
        rr.ensure_model(base=tmp_path)
    assert not list(rr.model_path(base=tmp_path).glob("*"))


def test_cli_rerank_flag(engram_home, tmp_path, monkeypatch):
    import engram.cli as cli
    s = searcher(tmp_path)
    calls = []
    real = s.search
    monkeypatch.setattr(s, "search", lambda *a, **k: (calls.append(k), real(*a, **k))[1])
    monkeypatch.setattr(cli, "_searcher", lambda *a, **k: s)
    runner = CliRunner()
    for args in ([], ["--rerank"], ["--no-rerank"]):
        assert runner.invoke(app, ["search", "music", *args]).exit_code == 0
    assert [c["rerank"] for c in calls] == [None, True, False]


def test_benchmark_runners_accept_rerank(monkeypatch):
    monkeypatch.setattr(rr, "get_reranker", lambda cfg: rr.CrossEncoder(TINY))

    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, ROOT / "benchmarks" / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    lme = load("lme", "longmemeval_bench.py").run_longmemeval(
        ROOT / "tests" / "fixtures" / "longmemeval_sample.json", backend="sqlitevec", rerank=True)
    assert lme["rerank"] is True and lme["questions"] == 4
    loc = load("locomo", "locomo_bench.py").run_locomo(
        ROOT / "tests" / "fixtures" / "locomo_sample.json", backend="sqlitevec", rerank=True)
    assert loc["rerank"] is True and loc["questions"] == 5


def test_setup_reranker_command(engram_home, monkeypatch):
    import json

    from engram import config as cfg_mod
    monkeypatch.setattr(rr, "ensure_model", lambda model=rr.DEFAULT_MODEL, **kw: TINY)
    cfg_mod.ensure_engram_dir()
    cfg_mod.CONFIG_PATH.write_text(json.dumps({"hybrid_weight": 0.5}))
    runner = CliRunner()
    result = runner.invoke(app, ["setup-reranker"])
    assert result.exit_code == 0, result.output
    assert json.loads(cfg_mod.CONFIG_PATH.read_text()) == {"hybrid_weight": 0.5, "reranker": True}
    assert cfg_mod.load_config()["reranker"] is True
    result = runner.invoke(app, ["setup-reranker", "--disable"])
    assert result.exit_code == 0
    assert json.loads(cfg_mod.CONFIG_PATH.read_text())["reranker"] is False


def test_setup_reranker_reports_failure(engram_home, monkeypatch):
    def fail(model=rr.DEFAULT_MODEL, **kw):
        raise rr.RerankerUnavailable("offline")

    monkeypatch.setattr(rr, "ensure_model", fail)
    result = CliRunner().invoke(app, ["setup-reranker"])
    assert result.exit_code == 1 and "offline" in result.output
