"""Temporal boosting (engram.temporal) and preference summaries (engram.preferences)."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engram.backends import sqlitevec_backend as sv
from engram.chateau import Chateau
from engram.config import DEFAULT_CONFIG
from engram.convo_miner import ConvoMiner
from engram.indexing import index_drawers
from engram.preferences import preference_mentions, preference_summary
from engram.searcher import Searcher
from engram.temporal import temporal_closeness, time_reference

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# time_reference / temporal_closeness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query, expected", [
    ("what did I buy two weeks ago?", (14, 5)),
    ("the restaurant from 3 days ago", (3, 2)),
    ("a couple of months ago I started a course", (60, 10)),
    ("who did I meet a year ago", (365, 30)),
    ("what did I cook yesterday", (1, 1)),
    ("the day before yesterday", (2, 1)),
    ("plans I made last week", (7, 3)),
    ("what did I say last month", (30, 7)),
    ("How many days ago did I go hiking?", None),  # asks for a count, names no time
    ("pizza with extra days ago", None),             # no number word glued to "extra"
    ("tell me about Rome", None),
])
def test_time_reference(query, expected):
    assert time_reference(query) == expected


def at(days):
    return (NOW - timedelta(days=days)).isoformat()


def test_temporal_closeness_window():
    ref = (14, 5)
    assert temporal_closeness(at(14), NOW, ref) == 1.0
    assert temporal_closeness(at(18), NOW, ref) == 1.0
    assert temporal_closeness(at(24), NOW, ref) == pytest.approx(0.5)
    assert temporal_closeness(at(40), NOW, ref) == 0.0
    assert temporal_closeness("", NOW, ref) == 0.0
    assert temporal_closeness("not a date", NOW, ref) == 0.0
    assert temporal_closeness("2026-09-27T12:00:00", NOW, ref) == 1.0  # naive = UTC


class FixedBackend:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, n=10, where=None):
        return [dict(h, metadata=dict(h["metadata"])) for h in self.hits][:n]


DATED = [
    {"id": "recent", "text": "Bought a new lamp for the desk.", "score": 0.60,
     "metadata": {"timestamp": (NOW - timedelta(days=1)).isoformat()}},
    {"id": "two-weeks", "text": "Bought hiking boots at the outlet.", "score": 0.55,
     "metadata": {"timestamp": (NOW - timedelta(days=15)).isoformat()}},
]


def dated_searcher(tmp_path, config=None):
    return Searcher(FixedBackend(DATED), Chateau(chateau_path=tmp_path / "c"),
                    config or {"hybrid_weight": 0.0})


def test_temporal_and_preferences_on_by_default():
    assert DEFAULT_CONFIG["temporal_weight"] == 0.4
    assert DEFAULT_CONFIG["preference_summaries"] is True


def test_temporal_boost_is_off_without_config_key(tmp_path):
    hits = dated_searcher(tmp_path).search("what did I buy two weeks ago", no_decay=True, now=NOW)
    assert [h["id"] for h in hits] == ["recent", "two-weeks"]


def test_temporal_boost_favours_the_named_time(tmp_path):
    hits = dated_searcher(tmp_path).search("what did I buy two weeks ago", no_decay=True,
                                           temporal_weight=0.4, now=NOW)
    assert [h["id"] for h in hits] == ["two-weeks", "recent"]
    assert hits[0]["temporal_closeness"] == 1.0
    assert hits[0]["final_score"] == round(0.55 * 1.4, 4)
    # From config too, and a query without a time phrase is untouched
    s = dated_searcher(tmp_path, {"hybrid_weight": 0.0, "temporal_weight": 0.4})
    assert s.search("what did I buy two weeks ago", no_decay=True, now=NOW)[0]["id"] == "two-weeks"
    assert s.search("what did I buy", no_decay=True, now=NOW)[0]["id"] == "recent"


# ---------------------------------------------------------------------------
# Preference summaries
# ---------------------------------------------------------------------------

def test_preference_mentions():
    assert preference_summary("I prefer window seats. Can you book me a flight?") == \
        "User has mentioned: window seats"
    assert preference_mentions(
        "I'm really into photography. I use Adobe Premiere Pro for editing.") == \
        ["photography", "adobe premiere pro for editing"]
    assert preference_mentions(
        "I've been struggling with my sleep schedule, anyway what's the capital of France?") == \
        ["my sleep schedule"]
    assert preference_summary("Tell me about the history of Rome.") is None
    assert preference_summary("I like it.") is None  # too short to mean anything


def test_index_drawers_accepts_extra_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    backend = sv.SqliteVecBackend(db_path=tmp_path / "vec.db")
    n = index_drawers(backend, [("d1", "main text of the drawer", {}, ["extra summary text"]),
                                ("d2", "another drawer", {})])
    assert n == backend.count() == 3


def test_convo_miner_indexes_preference_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    msg = {"role": "user", "timestamp": "", "id": "m1",
           "text": "Quick question about taxes first. Also, I've been struggling with "
                   "insomnia lately and I prefer herbal tea in the evening."}
    counts = {}
    for enabled in (False, True):
        backend = sv.SqliteVecBackend(db_path=tmp_path / f"vec{enabled}.db")
        palace = Chateau(chateau_path=tmp_path / f"c{enabled}")
        ConvoMiner(palace, backend, {"preference_summaries": enabled}).store_messages([msg], "w", "r")
        counts[enabled] = backend.count()
        assert [d.content for d in palace.iter_drawers()] == [msg["text"]]  # drawer stays verbatim
    assert counts == {False: 1, True: 2}


# ---------------------------------------------------------------------------
# LongMemEval runner with the new options
# ---------------------------------------------------------------------------

def _bench():
    spec = importlib.util.spec_from_file_location("lme", ROOT / "benchmarks" / "longmemeval_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lme_date():
    bench = _bench()
    assert bench._lme_date("2023/05/20 (Sat) 02:21") == datetime(2023, 5, 20, 2, 21, tzinfo=timezone.utc)
    assert bench._lme_date("") is None


def test_longmemeval_runner_with_temporal_and_preferences():
    result = _bench().run_longmemeval(ROOT / "tests" / "fixtures" / "longmemeval_sample.json",
                                      backend="sqlitevec", hybrid_weight=0.3,
                                      temporal_weight=0.4, preferences=True)
    assert result["questions"] == 4 and result["recall_any@5"] == 1.0
    assert result["temporal_weight"] == 0.4 and result["preferences"] is True
