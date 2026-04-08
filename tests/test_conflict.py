"""Tests for engram.conflict — contradiction detection and resolver."""

import pytest
from pathlib import Path

from engram.conflict import (
    ConflictDetector,
    ConflictResolver,
    detect_text_conflicts,
    Conflict,
    _extract_entity,
    _format_conflict,
)
from engram.knowledge_graph import KnowledgeGraph, Triple


@pytest.fixture
def kg(tmp_path):
    return KnowledgeGraph(db_path=tmp_path / "conflict_test.db")


# ---------------------------------------------------------------------------
# Text conflict detection
# ---------------------------------------------------------------------------

def test_detect_no_conflicts_in_empty_kg(kg):
    conflicts = detect_text_conflicts("Maya finished the auth migration.", kg)
    assert conflicts == []


def test_detect_assignment_conflict(kg):
    kg.add("Maya", "assigned_to", "auth-migration")
    # Text claims Soren finished it
    conflicts = detect_text_conflicts("Soren finished the auth-migration project.", kg)
    assert len(conflicts) >= 1
    assert any(c.type == "assignment" for c in conflicts)


def test_detect_no_conflict_same_person(kg):
    kg.add("Maya", "assigned_to", "auth-migration")
    conflicts = detect_text_conflicts("Maya finished auth-migration.", kg)
    # Same person — no conflict
    assert not any(c.type == "assignment" for c in conflicts)


# ---------------------------------------------------------------------------
# KG tenure conflicts
# ---------------------------------------------------------------------------

def test_detector_finds_tenure_conflict(kg):
    kg.add("Kai", "assigned_to", "orion")
    kg.add("Kai", "assigned_to", "driftwood")  # both active simultaneously
    detector = ConflictDetector(kg)
    conflicts = detector.detect_all()
    assert len(conflicts) >= 1
    assert all(c.type == "tenure" for c in conflicts)


def test_detector_no_conflict_after_invalidation(kg):
    kg.add("Kai", "assigned_to", "orion")
    kg.invalidate("Kai", "assigned_to", "orion", ended="2026-01-01")
    kg.add("Kai", "assigned_to", "driftwood")
    detector = ConflictDetector(kg)
    conflicts = detector.detect_all()
    assert len(conflicts) == 0


def test_detector_no_conflict_different_predicates(kg):
    kg.add("Kai", "works_on", "orion")
    kg.add("Kai", "manages", "orion")
    detector = ConflictDetector(kg)
    conflicts = detector.detect_all()
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# Conflict dataclass
# ---------------------------------------------------------------------------

def test_conflict_label_tenure():
    c = Conflict(type="tenure", description="test")
    assert "TENURE" in c.label()
    assert "🔴" in c.label()


def test_conflict_label_assignment():
    c = Conflict(type="assignment", description="test")
    assert "ASSIGNMENT" in c.label()


def test_conflict_label_date():
    c = Conflict(type="date", description="test")
    assert "DATE" in c.label()


# ---------------------------------------------------------------------------
# Non-interactive resolver
# ---------------------------------------------------------------------------

def test_resolve_non_interactive_keep(kg):
    kg.add("Kai", "assigned_to", "orion")
    kg.add("Kai", "assigned_to", "driftwood")
    resolver = ConflictResolver(kg)
    conflicts = resolver.detect()
    resolved = resolver.resolve_non_interactive(conflicts, policy="keep")
    assert resolved == len(conflicts)


def test_resolve_non_interactive_skip(kg):
    kg.add("Kai", "assigned_to", "orion")
    kg.add("Kai", "assigned_to", "driftwood")
    resolver = ConflictResolver(kg)
    conflicts = resolver.detect()
    resolved = resolver.resolve_non_interactive(conflicts, policy="skip")
    assert resolved == 0


def test_resolver_detect_returns_list(kg):
    resolver = ConflictResolver(kg)
    conflicts = resolver.detect()
    assert isinstance(conflicts, list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_extract_entity_from_quoted():
    result = _extract_entity('"auth-migration" completed')
    assert result == "auth-migration"


def test_extract_entity_none():
    result = _extract_entity("no quotes here")
    assert result is None


def test_format_conflict_with_triple():
    t = Triple(subject="Kai", predicate="works_on", object="Orion", valid_from="2025-01-01")
    c = Conflict(type="tenure", description="test", stored_triple=t, incoming_text="new claim")
    formatted = _format_conflict(c)
    assert "Kai" in formatted
    assert "Orion" in formatted


def test_format_conflict_no_triple():
    c = Conflict(type="date", description="stale deadline")
    formatted = _format_conflict(c)
    assert "stale deadline" in formatted
