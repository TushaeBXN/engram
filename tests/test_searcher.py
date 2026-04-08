"""Tests for engram.searcher — recency-weighted semantic search."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from engram.chateau import Chateau, Drawer
from engram.searcher import Searcher, _age_days, _build_where


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def palace(tmp_path):
    return Chateau(chateau_path=tmp_path)


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.search.return_value = []
    backend.count.return_value = 0
    return backend


@pytest.fixture
def searcher(palace, mock_backend):
    cfg = {
        "decay_factor": 0.005,
        "decay_max_days": 90,
        "vector_backend": "chromadb",
    }
    return Searcher(mock_backend, palace, cfg)


# ---------------------------------------------------------------------------
# _age_days
# ---------------------------------------------------------------------------

def test_age_days_now():
    ts = datetime.now(timezone.utc).isoformat()
    age = _age_days(ts)
    assert 0.0 <= age < 1.0


def test_age_days_one_week_ago():
    ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    age = _age_days(ts)
    assert 6.0 < age < 8.0


def test_age_days_empty():
    assert _age_days("") == 0.0


def test_age_days_invalid():
    assert _age_days("not-a-date") == 0.0


# ---------------------------------------------------------------------------
# _build_where
# ---------------------------------------------------------------------------

def test_build_where_all_none():
    assert _build_where(None, None, None) == {}


def test_build_where_wing_only():
    assert _build_where("myapp", None, None) == {"wing": "myapp"}


def test_build_where_all_fields():
    w = _build_where("myapp", "auth", "facts")
    assert w == {"wing": "myapp", "room": "auth", "hall": "facts"}


# ---------------------------------------------------------------------------
# Recency weighting
# ---------------------------------------------------------------------------

def test_recency_boost_applied(searcher, mock_backend):
    now_ts = datetime.now(timezone.utc).isoformat()
    mock_backend.search.return_value = [
        {"id": "1", "text": "recent content", "metadata": {"timestamp": now_ts}, "score": 0.8},
    ]
    results = searcher.search("query", n=1)
    assert len(results) == 1
    assert results[0]["final_score"] >= results[0]["semantic_score"]


def test_recency_boost_older_lower(searcher, mock_backend):
    new_ts = datetime.now(timezone.utc).isoformat()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=80)).isoformat()
    mock_backend.search.return_value = [
        {"id": "1", "text": "new content", "metadata": {"timestamp": new_ts}, "score": 0.8},
        {"id": "2", "text": "old content", "metadata": {"timestamp": old_ts}, "score": 0.8},
    ]
    results = searcher.search("query", n=2)
    assert results[0]["final_score"] >= results[1]["final_score"]


def test_no_decay_flag(searcher, mock_backend):
    ts = datetime.now(timezone.utc).isoformat()
    mock_backend.search.return_value = [
        {"id": "1", "text": "content", "metadata": {"timestamp": ts}, "score": 0.9},
    ]
    results = searcher.search("query", n=1, no_decay=True)
    assert results[0]["recency_boost"] == 0.0
    assert results[0]["final_score"] == results[0]["semantic_score"]


def test_pinned_bypasses_decay(searcher, mock_backend):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    mock_backend.search.return_value = [
        {"id": "1", "text": "pinned content", "metadata": {"timestamp": old_ts, "pinned": True}, "score": 0.7},
    ]
    results = searcher.search("query", n=1)
    assert results[0]["pinned"] is True
    assert results[0]["recency_boost"] == 0.0


# ---------------------------------------------------------------------------
# search returns empty on no results
# ---------------------------------------------------------------------------

def test_search_no_results(searcher, mock_backend):
    mock_backend.search.return_value = []
    results = searcher.search("nothing here")
    assert results == []


# ---------------------------------------------------------------------------
# Results are sorted by final_score descending
# ---------------------------------------------------------------------------

def test_results_sorted(searcher, mock_backend):
    ts = datetime.now(timezone.utc).isoformat()
    mock_backend.search.return_value = [
        {"id": "1", "text": "a", "metadata": {"timestamp": ts}, "score": 0.3},
        {"id": "2", "text": "b", "metadata": {"timestamp": ts}, "score": 0.9},
        {"id": "3", "text": "c", "metadata": {"timestamp": ts}, "score": 0.6},
    ]
    results = searcher.search("query", n=3)
    scores = [r["final_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
