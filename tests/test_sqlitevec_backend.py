"""Tests for the dependency-free SQLite vector backend."""

import pytest

from engram.backends import get_backend
from engram.backends import sqlitevec_backend as sv


@pytest.fixture
def backend(tmp_path, monkeypatch):
    # Force the keyword fallback even if sentence-transformers is installed,
    # so results are deterministic and no model is downloaded.
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    return sv.SqliteVecBackend(db_path=tmp_path / "vec.db")


DOCS = {
    "auth": "We migrated authentication to OAuth2 tokens",
    "tabs": "I prefer tabs over spaces for indentation",
    "deploy": "Deployed version two to production yesterday",
    "cache": "Root cause was a stale cache key in redis",
    "float": "Always use float32 on CPU because bfloat16 is slow",
}


@pytest.fixture
def filled(backend):
    for doc_id, text in DOCS.items():
        backend.add(doc_id, text, {"wing": "work" if doc_id != "tabs" else "personal"})
    return backend


@pytest.mark.parametrize(
    "query, expected",
    [
        ("OAuth2 authentication tokens", "auth"),
        ("tabs or spaces indentation", "tabs"),
        ("production deploy", "deploy"),
        ("redis cache key", "cache"),
        ("float32 CPU", "float"),
    ],
)
def test_keyword_fallback_ranks_matching_doc_first(filled, query, expected):
    results = filled.search(query, n=5)
    assert results[0]["id"] == expected
    assert results[0]["score"] > results[1]["score"]


def test_unrelated_docs_score_near_zero(filled):
    scores = [r["score"] for r in filled.search("OAuth2 authentication tokens", n=5)]
    assert scores[0] > 0.5
    assert all(abs(s) < 0.2 for s in scores[1:])


def test_hashed_bow_is_deterministic_and_normalised():
    a = sv._hashed_bow("Hello hello world")
    assert a == sv._hashed_bow("hello HELLO world")
    assert sum(x * x for x in a) == pytest.approx(1.0)
    assert len(a) == sv._EMBED_DIM


def test_empty_text_gives_zero_vector_without_error(backend):
    assert sv._hashed_bow("!!!") == [0.0] * sv._EMBED_DIM
    backend.add("empty", "", {})
    assert backend.search("anything", n=1)[0]["score"] == 0.0


def test_where_filter(filled):
    results = filled.search("tabs spaces", n=5, where={"wing": "work"})
    assert "tabs" not in {r["id"] for r in results}
    assert all(r["metadata"]["wing"] == "work" for r in results)


def test_n_limits_results(filled):
    assert len(filled.search("cache", n=2)) == 2


def test_upsert_count_delete(backend):
    backend.add("a", "first version", {"v": 1})
    backend.add("a", "second version", {"v": 2})
    assert backend.count() == 1
    assert backend.search("second", n=1)[0]["metadata"] == {"v": 2}
    backend.update("a", "third version", {"v": 3})
    assert backend.search("third", n=1)[0]["text"] == "third version"
    backend.delete("a")
    assert backend.count() == 0
    assert backend.search("third") == []


def test_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    path = tmp_path / "vec.db"
    sv.SqliteVecBackend(db_path=path).add("x", "persistent redis note", {})
    assert sv.SqliteVecBackend(db_path=path).search("redis", n=1)[0]["id"] == "x"


def test_get_backend_returns_sqlitevec(tmp_path):
    assert isinstance(get_backend("sqlitevec", db_path=tmp_path / "v.db"), sv.SqliteVecBackend)
