"""Tests for engram.watcher — watch mode."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engram.watcher import EngramWatcher


@pytest.fixture
def watcher(tmp_path):
    return EngramWatcher(tmp_path, wing="test", mode="files")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_watcher_init(tmp_path):
    w = EngramWatcher(tmp_path, wing="myapp", mode="files")
    assert w.wing == "myapp"
    assert w.mode == "files"
    assert w.path == tmp_path


def test_watcher_default_wing(tmp_path):
    w = EngramWatcher(tmp_path)
    assert w.wing == "default"


def test_watcher_default_mode(tmp_path):
    w = EngramWatcher(tmp_path)
    assert w.mode == "files"


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------

def test_handle_event_skips_binary(watcher, tmp_path):
    """Binary file extensions should be silently skipped."""
    mock_miner = MagicMock()
    mock_console = MagicMock()
    watcher._handle_event("created", str(tmp_path / "image.png"), mock_miner, mock_console)
    mock_miner.mine.assert_not_called()


def test_handle_event_mines_py_file(watcher, tmp_path):
    """Python files should be mined."""
    mock_miner = MagicMock()
    mock_miner.mine.return_value = [MagicMock()]
    mock_console = MagicMock()
    py_file = tmp_path / "module.py"
    py_file.write_text("def foo(): pass")
    watcher._handle_event("created", str(py_file), mock_miner, mock_console)
    mock_miner.mine.assert_called_once()


def test_handle_event_mines_md_file(watcher, tmp_path):
    """Markdown files should be mined."""
    mock_miner = MagicMock()
    mock_miner.mine.return_value = [MagicMock()]
    mock_console = MagicMock()
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Notes")
    watcher._handle_event("modified", str(md_file), mock_miner, mock_console)
    mock_miner.mine.assert_called_once()


def test_handle_event_handles_miner_error(watcher, tmp_path):
    """Errors from miner should not propagate — logged to console instead."""
    mock_miner = MagicMock()
    mock_miner.mine.side_effect = RuntimeError("miner failed")
    mock_console = MagicMock()
    py_file = tmp_path / "broken.py"
    py_file.write_text("x = 1")
    # Should not raise
    watcher._handle_event("created", str(py_file), mock_miner, mock_console)


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

def test_stop_sets_running_false(watcher):
    watcher._running = True
    mock_obs = MagicMock()
    watcher._observer = mock_obs
    watcher.stop()
    assert watcher._running is False
    mock_obs.stop.assert_called_once()
