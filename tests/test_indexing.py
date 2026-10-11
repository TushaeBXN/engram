"""Chunked indexing: long drawers are fully searchable, one result per drawer."""

import importlib.util
import json
from pathlib import Path

import pytest

from engram.backends import sqlitevec_backend as sv
from engram.backends.chromadb_backend import _chroma_where
from engram.chateau import Chateau
from engram.indexing import (
    CHUNK_CHARS,
    chunk_text,
    drawer_id_of,
    index_drawer,
    index_drawers,
    unindex_drawer,
)
from engram.searcher import Searcher

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_get_embedder", lambda: None)
    return sv.SqliteVecBackend(db_path=tmp_path / "vec.db")


LONG = ("I am writing up notes about my garden and the tomatoes. " * 60
        + "By the way, my new car is a blue Subaru Outback.")


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

def test_short_text_is_one_chunk():
    assert chunk_text("  hello world  ") == ["hello world"]
    assert chunk_text("   ") == []


def test_chunks_respect_size_and_cover_all_words():
    chunks = chunk_text(LONG)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    assert set(LONG.split()) == set(" ".join(chunks).split())
    assert "Subaru Outback" in chunks[-1]


def test_chunks_overlap_and_end_on_breaks():
    chunks = chunk_text(LONG, size=300, overlap=60)
    for a, b in zip(chunks, chunks[1:]):
        assert a.endswith(".")  # sentence boundary available in every window
        assert b.split()[0] in a.split()[-15:]  # overlap carried over


def test_unbreakable_text_still_splits():
    chunks = chunk_text("x" * 2500, size=1000, overlap=100)
    assert all(len(c) <= 1000 for c in chunks) and "".join(chunks).count("x") >= 2500


# ---------------------------------------------------------------------------
# index / unindex / search
# ---------------------------------------------------------------------------

def test_index_drawer_stores_chunks_with_drawer_id(backend):
    n = index_drawer(backend, "d1", LONG, {"wing": "w"})
    assert n == backend.count() > 1
    hit = backend.search("Subaru Outback car", n=1)[0]
    assert hit["metadata"]["drawer_id"] == "d1" and drawer_id_of(hit) == "d1"


def test_reindex_replaces_old_chunks(backend):
    index_drawer(backend, "d1", LONG, {})
    index_drawer(backend, "d1", "short replacement text", {})
    assert backend.count() == 1


def test_unindex_removes_chunks_and_legacy_entry(backend):
    backend.add("legacy", "pre-chunking entry stored under the bare id", {})
    index_drawer(backend, "d1", LONG, {})
    unindex_drawer(backend, "d1")
    unindex_drawer(backend, "legacy")
    assert backend.count() == 0


def test_drawer_id_of_legacy_hit():
    assert drawer_id_of({"id": "abc", "metadata": {}}) == "abc"
    assert drawer_id_of({"id": "abc::3", "metadata": {}}) == "abc"


def test_searcher_finds_fact_past_old_2000_char_limit(backend, tmp_path):
    assert LONG.index("Subaru") > 2000
    index_drawer(backend, "garden", LONG, {"wing": "w"})
    index_drawer(backend, "other", "Notes about the Subaru dealership hours on weekends", {"wing": "w"})
    hits = Searcher(backend, Chateau(chateau_path=tmp_path / "c"), {}).search(
        "blue Subaru Outback car", n=5, no_decay=True)
    ids = [h["id"] for h in hits]
    assert ids[0] == "garden"
    assert len(ids) == len(set(ids)), "chunks of one drawer must collapse into one result"


def test_chroma_where_combines_filters_with_and():
    assert _chroma_where({"wing": "w"}) == {"wing": "w"}
    assert _chroma_where({"wing": "w", "room": "r"}) == {"$and": [{"wing": "w"}, {"room": "r"}]}


# ---------------------------------------------------------------------------
# LongMemEval runner on the bundled sample (pipeline check, not a score)
# ---------------------------------------------------------------------------

def _bench():
    spec = importlib.util.spec_from_file_location("lme", ROOT / "benchmarks" / "longmemeval_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_longmemeval_runner_on_sample(tmp_path):
    out = tmp_path / "results.jsonl"
    result = _bench().run_longmemeval(ROOT / "tests" / "fixtures" / "longmemeval_sample.json",
                                      backend="sqlitevec", out=out)
    assert result["questions"] == 4
    assert result["recall_any@5"] == 1.0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert {r["question_id"] for r in rows} == {"q1", "q2", "q3", "q4"}
    assert set(result["by_type"]) == {"single-session-user", "single-session-assistant", "multi-session"}


def test_ndcg():
    ndcg = _bench()._ndcg_any
    assert ndcg(["a", "b"], {"a"}, 10) == 1.0
    assert 0 < ndcg(["x", "a"], {"a"}, 10) < 1.0
    assert ndcg(["x"], {"a"}, 10) == 0.0


# ---------------------------------------------------------------------------
# Batched indexing
# ---------------------------------------------------------------------------

def test_index_drawers_batches_into_one_write(backend, monkeypatch):
    calls = []
    real = backend.add_many
    monkeypatch.setattr(backend, "add_many", lambda items: (calls.append(len(items)), real(items)))
    n = index_drawers(backend, [("a", LONG, {"wing": "w"}), ("b", "short text here", {"wing": "w"})])
    assert calls == [n] and n == backend.count() > 2


def test_index_drawers_replace_false_skips_deletes(backend, monkeypatch):
    monkeypatch.setattr(backend, "delete_where", lambda where: pytest.fail("should not delete"))
    index_drawers(backend, [("new", "brand new drawer text", {})], replace=False)
    assert backend.count() == 1


def test_base_add_many_falls_back_to_add():
    from engram.backends.base import VectorBackend

    class Minimal(VectorBackend):
        def __init__(self):
            self.rows = {}
        def add(self, id, text, metadata):
            self.rows[id] = text
        def search(self, query, n=10, where=None):
            return []
        def delete(self, id):
            pass
        def delete_where(self, where):
            pass
        def count(self):
            return len(self.rows)
        def update(self, id, text, metadata):
            self.add(id, text, metadata)

    m = Minimal()
    m.add_many([("x", "one", {}), ("y", "two", {})])
    assert m.count() == 2


def test_convo_store_messages_indexes_once_per_call(tmp_path, backend, monkeypatch):
    from engram.convo_miner import ConvoMiner
    calls = []
    real = backend.add_many
    monkeypatch.setattr(backend, "add_many", lambda items: (calls.append(len(items)), real(items)))
    cm = ConvoMiner(Chateau(chateau_path=tmp_path / "c"), backend, {})
    msgs = [{"role": "user", "text": f"message number {i} about the deploy", "timestamp": "", "id": f"m{i}"}
            for i in range(5)]
    cm.store_messages(msgs, wing="w", room="r")
    assert calls == [5]
    cm.store_messages(msgs, wing="w", room="r")  # re-import: replaced, still no duplicates
    assert backend.count() == 5
