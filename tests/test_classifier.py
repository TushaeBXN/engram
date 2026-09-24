"""Tests for engram.classifier — content-based hall classification."""

from unittest.mock import MagicMock

import pytest

from engram.chateau import HALL_TYPES, Chateau
from engram.classifier import classify_hall, score_halls
from engram.convo_miner import ConvoMiner
from engram.miner import Miner


@pytest.fixture
def palace(tmp_path):
    return Chateau(chateau_path=tmp_path / "chateau")


# ---------------------------------------------------------------------------
# classify_hall
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("I prefer tabs over spaces and I'd rather keep lines short.", "preferences"),
        ("You should pin dependencies. Make sure CI runs on every PR.", "advice"),
        ("We deployed v2 yesterday and rolled back after the incident.", "events"),
        ("Turns out the root cause was a stale cache key.", "discoveries"),
        ("The database is configured in settings.py and uses postgres.", "facts"),
    ],
)
def test_classify_hall_picks_matching_hall(text, expected):
    hall, confidence = classify_hall(text)
    assert hall == expected
    assert 0.0 < confidence <= 1.0


def test_classify_hall_uses_fallback_when_nothing_matches():
    assert classify_hall("lorem ipsum dolor sit amet", fallback="discoveries") == ("discoveries", 0.0)


def test_classify_hall_uses_fallback_on_tie():
    # One preference pattern and one advice pattern: no clear winner.
    assert classify_hall("I prefer this. Make sure it works.", fallback="facts") == ("facts", 0.0)


def test_classify_hall_rejects_invalid_fallback():
    with pytest.raises(ValueError):
        classify_hall("anything", fallback="nonsense")


def test_score_halls_covers_every_hall():
    assert set(score_halls("")) == set(HALL_TYPES)


def test_score_halls_only_scans_the_start():
    text = "x" * 10_000 + " turns out the root cause was found"
    assert score_halls(text)["discoveries"] == 0


# ---------------------------------------------------------------------------
# Miner integration
# ---------------------------------------------------------------------------

def test_miner_classifies_prose_files_by_content(palace, tmp_path):
    note = tmp_path / "notes.md"
    note.write_text("Turns out the root cause was a missing index.")
    drawers = Miner(palace, MagicMock(), config={}).mine(note, wing="w")
    assert drawers[0].hall == "discoveries"


def test_miner_keeps_extension_hall_for_code(palace, tmp_path):
    code = tmp_path / "app.py"
    code.write_text("# I prefer this style\nx = 1\n")
    drawers = Miner(palace, MagicMock(), config={}).mine(code, wing="w")
    assert drawers[0].hall == "discoveries"


def test_miner_prose_without_signal_keeps_extension_hall(palace, tmp_path):
    note = tmp_path / "readme.txt"
    note.write_text("Plain words with nothing special in them at all.")
    drawers = Miner(palace, MagicMock(), config={}).mine(note, wing="w")
    assert drawers[0].hall == "facts"


# ---------------------------------------------------------------------------
# ConvoMiner integration
# ---------------------------------------------------------------------------

def test_convo_miner_classifies_user_preference(palace):
    cm = ConvoMiner(palace, MagicMock(), config={})
    msg = {"role": "user", "text": "I prefer small PRs, I'd rather review often.", "timestamp": None}
    assert cm._store_message(msg, "w", "r").hall == "preferences"


def test_convo_miner_falls_back_to_role(palace):
    cm = ConvoMiner(palace, MagicMock(), config={})
    msg = {"role": "assistant", "text": "Here is the summary of the file you sent.", "timestamp": None}
    assert cm._store_message(msg, "w", "r").hall == "discoveries"
