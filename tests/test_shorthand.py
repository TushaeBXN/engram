"""Tests for engram.shorthand — Engram Shorthand (ES) compression."""

import pytest
from engram.shorthand import (
    compress,
    decompress,
    compression_ratio,
    annotate_confidence,
    _compress_code_signature,
    _compact_args,
)


# ---------------------------------------------------------------------------
# Basic compress / decompress round-trips
# ---------------------------------------------------------------------------

def test_compress_returns_string():
    result = compress("The authentication module is important.")
    assert isinstance(result, str)


def test_compress_shorter_than_input():
    text = (
        "The authentication module is a critical component that has a dependency "
        "on the database and is responsible for verifying user credentials."
    )
    result = compress(text)
    assert len(result) < len(text)


def test_compression_ratio_above_one():
    text = "The authentication module is a critical important database component."
    compressed = compress(text)
    ratio = compression_ratio(text, compressed)
    assert ratio >= 1.0


def test_decompress_reverses_symbols():
    # Symbols that have clear inverses should round-trip
    text = "therefore the result implies success"
    compressed = compress(text)
    decompressed = decompress(compressed)
    # Key concepts should survive the round-trip
    assert "∴" not in decompressed or "therefore" in decompressed


def test_compress_empty_string():
    assert compress("") == ""


def test_decompress_empty_string():
    assert decompress("") == ""


# ---------------------------------------------------------------------------
# Confidence annotation
# ---------------------------------------------------------------------------

def test_annotate_confidence():
    result = annotate_confidence("Auth uses JWT", 4)
    assert "★★★★" in result
    assert "Auth uses JWT" in result


def test_compress_with_confidence():
    result = compress("auth uses JWT", confidence=3)
    assert "★★★" in result


def test_confidence_clamped_low():
    result = annotate_confidence("test", 0)
    assert "★" in result


def test_confidence_clamped_high():
    result = annotate_confidence("test", 10)
    assert result.count("★") == 5


# ---------------------------------------------------------------------------
# Code-aware compression
# ---------------------------------------------------------------------------

def test_code_signature_python_func():
    code = "def authenticate(user: str, token: str) -> bool:"
    result = compress(code, is_code=True)
    assert "fn:authenticate" in result


def test_code_signature_async():
    code = "async def fetch_user(user_id: int) -> dict:"
    result = compress(code, is_code=True)
    assert "async_fn:fetch_user" in result


def test_code_signature_no_return():
    code = "def setup_logging(level: str):"
    result = compress(code, is_code=True)
    assert "fn:setup_logging" in result


def test_compact_args_basic():
    result = _compact_args("user: str, token: str")
    assert "user" in result
    assert "token" in result


def test_compact_args_strips_defaults():
    result = _compact_args("level: str = 'INFO', count: int = 0")
    assert "=" not in result


def test_compact_args_empty():
    assert _compact_args("") == ""


def test_decompress_code_signature():
    code = "def check_auth(user: str, token: str) -> bool:"
    compressed = compress(code, is_code=True)
    decompressed = decompress(compressed)
    assert "def" in decompressed
    assert "check_auth" in decompressed


# ---------------------------------------------------------------------------
# Diff compression
# ---------------------------------------------------------------------------

def test_diff_compression():
    diff = "+    def middleware_check(self):\n-    manual_verify()"
    result = compress(diff, is_diff=True, diff_filename="auth.py")
    assert "CHANGE:auth.py" in result
    assert "add:" in result
    assert "rm:" in result


def test_diff_decompress():
    diff = "+    new_feature()\n-    old_feature()"
    compressed = compress(diff, is_diff=True, diff_filename="app.py")
    decompressed = decompress(compressed)
    assert "Changes to app.py" in decompressed


# ---------------------------------------------------------------------------
# Symbol substitutions
# ---------------------------------------------------------------------------

def test_compress_therefore():
    result = compress("therefore this is correct")
    assert "∴" in result


def test_compress_implies():
    result = compress("auth failure implies logout")
    assert "→" in result


def test_compress_with_slash():
    result = compress("deploy with the new config")
    assert "w/" in result or "with" not in result


def test_compress_completed():
    result = compress("Maya completed the migration")
    assert "✓" in result or "completed" not in result.lower()


# ---------------------------------------------------------------------------
# Whitespace handling
# ---------------------------------------------------------------------------

def test_compress_strips_extra_whitespace():
    result = compress("auth   module   test")
    assert "  " not in result


def test_compress_strips_blank_lines():
    result = compress("line1\n\n\n\nline2")
    assert "\n\n\n" not in result
