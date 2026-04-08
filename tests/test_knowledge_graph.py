"""Tests for engram.knowledge_graph — temporal SQLite KG."""

import pytest
from pathlib import Path
from engram.knowledge_graph import KnowledgeGraph, Triple


@pytest.fixture
def kg(tmp_path):
    return KnowledgeGraph(db_path=tmp_path / "test_kg.db")


# ---------------------------------------------------------------------------
# Add / query
# ---------------------------------------------------------------------------

def test_add_triple(kg):
    t = kg.add("Kai", "works_on", "Orion", valid_from="2025-06-01")
    assert t.id is not None
    assert t.subject == "Kai"
    assert t.predicate == "works_on"
    assert t.object == "Orion"


def test_count_empty(kg):
    assert kg.count() == 0


def test_count_after_add(kg):
    kg.add("A", "rel", "B")
    kg.add("C", "rel", "D")
    assert kg.count() == 2


def test_query_by_subject(kg):
    kg.add("Kai", "works_on", "Orion")
    kg.add("Maya", "works_on", "Driftwood")
    results = kg.query("Kai")
    assert len(results) == 1
    assert results[0].subject == "Kai"


def test_query_by_object(kg):
    kg.add("Kai", "works_on", "Orion")
    kg.add("Maya", "contributes_to", "Orion")
    results = kg.query("Orion")
    assert len(results) == 2


def test_query_with_predicate(kg):
    kg.add("Kai", "works_on", "Orion")
    kg.add("Kai", "manages", "Team-Alpha")
    results = kg.query("Kai", predicate="works_on")
    assert len(results) == 1
    assert results[0].predicate == "works_on"


def test_find_exact(kg):
    kg.add("A", "rel", "B")
    kg.add("A", "rel", "C")
    results = kg.find(subject="A", predicate="rel", obj="B")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Temporal operations
# ---------------------------------------------------------------------------

def test_invalidate(kg):
    kg.add("Kai", "works_on", "Orion", valid_from="2025-01-01")
    count = kg.invalidate("Kai", "works_on", "Orion", ended="2026-01-01")
    assert count == 1
    triples = kg.find(subject="Kai", predicate="works_on", obj="Orion")
    assert all(t.valid_until is not None for t in triples)


def test_is_active_no_bounds(kg):
    t = kg.add("A", "rel", "B")
    assert t.is_active() is True


def test_is_active_with_valid_from_past(kg):
    t = kg.add("A", "rel", "B", valid_from="2020-01-01")
    assert t.is_active() is True


def test_is_active_not_yet_valid(kg):
    t = Triple(subject="A", predicate="rel", object="B", valid_from="2099-01-01")
    assert t.is_active() is False


def test_is_active_expired(kg):
    t = Triple(subject="A", predicate="rel", object="B", valid_until="2020-01-01")
    assert t.is_active() is False


def test_timeline_sorted(kg):
    kg.add("Kai", "role", "engineer", valid_from="2023-01-01")
    kg.add("Kai", "role", "lead", valid_from="2024-01-01")
    kg.add("Kai", "role", "director", valid_from="2025-01-01")
    timeline = kg.timeline("Kai")
    dates = [t.valid_from for t in timeline]
    assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def test_detect_tenure_conflict(kg):
    # Two active triples for same (subject, predicate) with different objects
    kg.add("Kai", "assigned_to", "project-A")
    kg.add("Kai", "assigned_to", "project-B")
    conflicts = kg.detect_tenure_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "tenure_conflict"


def test_no_conflict_different_predicates(kg):
    kg.add("Kai", "works_on", "Orion")
    kg.add("Kai", "manages", "Orion")
    conflicts = kg.detect_tenure_conflicts()
    assert len(conflicts) == 0


def test_no_conflict_after_invalidation(kg):
    kg.add("Kai", "assigned_to", "project-A")
    kg.invalidate("Kai", "assigned_to", "project-A", ended="2026-01-01")
    kg.add("Kai", "assigned_to", "project-B")
    conflicts = kg.detect_tenure_conflicts()
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Missing valid_from
# ---------------------------------------------------------------------------

def test_triples_missing_valid_from(kg):
    kg.add("A", "rel", "B")         # no valid_from
    kg.add("C", "rel", "D", valid_from="2025-01-01")
    missing = kg.triples_missing_valid_from()
    assert len(missing) == 1


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_by_id(kg):
    t = kg.add("X", "knows", "Y")
    ok = kg.delete_by_id(t.id)
    assert ok is True
    assert kg.count() == 0


def test_delete_nonexistent(kg):
    ok = kg.delete_by_id(99999)
    assert ok is False
