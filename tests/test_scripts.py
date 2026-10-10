"""Smoke tests: the shipped examples and benchmark runners must actually run."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated_env(tmp_path):
    """Run scripts with a throwaway ~/.engram and the dependency-free backend."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["ENGRAM_VECTOR_BACKEND"] = "sqlitevec"
    return env


def _run(args, env, cwd=ROOT):
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


def test_basic_mining_example(isolated_env, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "notes.md").write_text("Turns out the root cause was a stale cache key.")
    result = _run(["examples/basic_mining.py", str(project), "--wing", "demo"], isolated_env)
    assert result.returncode == 0, result.stderr
    assert "Mined 1 drawer(s) into wing 'demo'" in result.stdout


def test_convo_import_example(isolated_env, tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "chat.md").write_text(
        "**Human:** I prefer small pull requests over big ones.\n\n"
        "**Assistant:** Noted, I will keep each change focused and small.\n"
    )
    result = _run(["examples/convo_import.py", str(export)], isolated_env)
    assert result.returncode == 0, result.stderr
    assert "Imported" in result.stdout


def test_longmemeval_compression_only(isolated_env):
    result = _run(["benchmarks/longmemeval_bench.py", "--compression-only"], isolated_env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout[result.stdout.index("{"):])
    assert set(payload) == {"factual", "code", "mixed"}
    assert all(r["mean"] >= 1.0 for r in payload.values())


@pytest.mark.parametrize("script", ["benchmarks/longmemeval_bench.py", "benchmarks/locomo_bench.py"])
def test_benchmark_runners_handle_missing_dataset(isolated_env, tmp_path, script):
    result = _run([script, "--data-dir", str(tmp_path / "missing")], isolated_env)
    assert result.returncode == 0, result.stderr
    assert "Dataset not found" in result.stdout
