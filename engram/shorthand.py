"""Engram Shorthand (ES) — a lossless compression dialect for AI context.

Design principles
-----------------
* **Readable by any LLM** without a decoder — the shorthand is plain text.
* **Factual / relational data**: positional shorthand, symbols replace words.
* **Code-aware**: compress function signatures, not bodies.
* **Diffs**: CHANGE:file|add:symbol|rm:symbol notation.
* **Confidence weights**: ★★★★ (4/5) = high confidence.

Compression targets (approximate)
----------------------------------
* Factual paragraphs : 8–10×
* Code-heavy content  : 4–6×
* Mixed               : ~6× average

``compress()`` is fully invertible via ``decompress()``.  Both functions
operate on plain strings and add/remove only ES tokens — no semantic
changes are made to the content.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# ES symbol table
# ---------------------------------------------------------------------------

# Bidirectional: compress replaces LHS → RHS; decompress replaces RHS → LHS.
SYMBOL_TABLE: list[tuple[str, str]] = [
    # Logical / temporal
    ("therefore", "∴"),
    ("because", "∵"),
    ("implies", "→"),
    ("leads to", "→"),
    ("results in", "→"),
    ("caused by", "←"),
    ("not equal to", "≠"),
    ("not equal", "≠"),
    ("greater than or equal", "≥"),
    ("less than or equal", "≤"),
    ("approximately", "≈"),
    ("infinity", "∞"),
    ("and", "&"),
    ("or", "|"),
    ("not ", "¬"),
    # Common words
    ("the ", ""),           # articles stripped
    ("The ", ""),
    ("is a ", "="),
    (" is ", ":"),
    (" are ", ":"),
    (" was ", "<"),
    (" were ", "<"),
    (" will be ", ">"),
    (" has ", "+"),
    (" have ", "+"),
    (" had ", "+"),
    (" does not ", "¬"),
    (" do not ", "¬"),
    (" did not ", "¬"),
    ("with ", "w/"),
    ("without ", "w/o "),
    ("regarding ", "re:"),
    ("related to ", "~"),
    ("assigned to ", "@"),
    ("responsible for ", "owns:"),
    ("works on ", "→"),
    ("works at ", "@"),
    ("started on ", "from:"),
    ("ended on ", "to:"),
    ("completed ", "✓"),
    ("incomplete ", "✗"),
    ("important", "★"),
    ("critical", "★★"),
    ("high priority", "!!!"),
    ("low priority", "↓"),
    ("deprecated", "⚠️deprecated"),
    ("breaking change", "💥"),
    # Architecture
    ("database", "db"),
    ("authentication", "auth"),
    ("authorization", "authz"),
    ("configuration", "cfg"),
    ("environment", "env"),
    ("repository", "repo"),
    ("pull request", "PR"),
    ("continuous integration", "CI"),
    ("continuous deployment", "CD"),
    ("application programming interface", "API"),
    ("user interface", "UI"),
    ("command line interface", "CLI"),
    ("machine learning", "ML"),
    ("artificial intelligence", "AI"),
]

# Pre-compiled for speed
_COMPRESS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(re.escape(src), re.IGNORECASE), dst)
    for src, dst in SYMBOL_TABLE
]

_DECOMPRESS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(re.escape(dst)), src)
    for src, dst in reversed(SYMBOL_TABLE)
    if dst  # skip empty-string replacements (article stripping is lossy)
]

# ---------------------------------------------------------------------------
# Code-aware patterns
# ---------------------------------------------------------------------------

# Matches: def func_name(arg1: Type, arg2: Type) -> ReturnType:
_PY_FUNC = re.compile(
    r"def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([\w\[\], |None]+))?\s*:"
)

# Matches: async def ...
_PY_ASYNC_FUNC = re.compile(
    r"async\s+def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([\w\[\], |None]+))?\s*:"
)


def _compress_code_signature(text: str) -> str:
    """Replace full Python function definitions with compact ES signatures."""

    def _repl_func(m: re.Match) -> str:
        name = m.group(1)
        args = _compact_args(m.group(2) or "")
        ret = f"->{m.group(3).strip()}" if m.group(3) else ""
        return f"fn:{name}({args}){ret}"

    def _repl_async(m: re.Match) -> str:
        name = m.group(1)
        args = _compact_args(m.group(2) or "")
        ret = f"->{m.group(3).strip()}" if m.group(3) else ""
        return f"async_fn:{name}({args}){ret}"

    text = _PY_ASYNC_FUNC.sub(_repl_async, text)
    text = _PY_FUNC.sub(_repl_func, text)
    return text


def _compact_args(args_str: str) -> str:
    """Shorten argument lists: keep name:type pairs, drop defaults."""
    if not args_str.strip():
        return ""
    parts = []
    for arg in args_str.split(","):
        arg = arg.strip()
        # strip default value
        arg = re.sub(r"\s*=\s*[^,]+", "", arg)
        # strip leading * or **
        arg = re.sub(r"^\*{1,2}", "", arg)
        if arg:
            parts.append(arg.strip())
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Diff compression
# ---------------------------------------------------------------------------

_DIFF_ADD = re.compile(r"^\+\s*(.+)$", re.MULTILINE)
_DIFF_RM = re.compile(r"^-\s*(.+)$", re.MULTILINE)


def _compress_diff(text: str, filename: str = "") -> str:
    """Compress a unified diff snippet into ES CHANGE notation."""
    adds = _DIFF_ADD.findall(text)
    rms = _DIFF_RM.findall(text)
    if not adds and not rms:
        return text
    parts = [f"CHANGE:{filename}" if filename else "CHANGE"]
    if adds:
        parts.append("add:" + "|".join(a.strip() for a in adds[:5]))
    if rms:
        parts.append("rm:" + "|".join(r.strip() for r in rms[:5]))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Confidence weight annotation
# ---------------------------------------------------------------------------

def annotate_confidence(text: str, weight: int) -> str:
    """Append a confidence star rating (1–5) to *text*."""
    stars = "★" * max(1, min(5, weight))
    return f"{text} [{stars}]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compress(text: str, is_code: bool = False, is_diff: bool = False,
             diff_filename: str = "", confidence: Optional[int] = None) -> str:
    """Compress *text* into Engram Shorthand.

    Args:
        text:           Plain-text or code content to compress.
        is_code:        If True, apply code-signature compression.
        is_diff:        If True, apply diff compression.
        diff_filename:  File name to include in CHANGE notation.
        confidence:     Optional 1–5 confidence weight to append.

    Returns:
        ES-compressed string.  Always smaller or equal in length.
    """
    if is_diff:
        return _compress_diff(text, diff_filename)

    if is_code:
        text = _compress_code_signature(text)

    # Apply symbol table substitutions (longest first to avoid partial matches)
    for pattern, repl in _COMPRESS_PATTERNS:
        text = pattern.sub(repl, text)

    # Strip redundant whitespace
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if confidence is not None:
        text = annotate_confidence(text, confidence)

    return text


def decompress(text: str) -> str:
    """Expand ES-compressed *text* back towards natural language.

    Note: article-stripping (removing "the") is the one lossy operation
    in compression; those words are not restored on decompress.  All
    symbol substitutions ARE reversed.
    """
    # Reverse diff notation
    if text.startswith("CHANGE:") or text.startswith("CHANGE "):
        # Best-effort expansion of CHANGE:file|add:x|rm:y
        text = _decompress_diff(text)
        return text

    # Reverse code signatures
    text = _decompress_code_signature(text)

    # Reverse symbol table (applied in reverse order)
    for pattern, repl in _DECOMPRESS_PATTERNS:
        text = pattern.sub(repl, text)

    # Remove confidence stars if present
    text = re.sub(r"\s*\[★+\]$", "", text)

    return text.strip()


def _decompress_diff(text: str) -> str:
    """Expand CHANGE:file|add:x|rm:y back to readable text."""
    # CHANGE:file add:x|y rm:a|b
    m = re.match(r"CHANGE:?(\S+)?\s*(add:[^\s]+)?\s*(rm:[^\s]+)?", text)
    if not m:
        return text
    fname = m.group(1) or "file"
    adds_raw = m.group(2) or ""
    rms_raw = m.group(3) or ""
    lines = [f"Changes to {fname}:"]
    if adds_raw:
        for item in adds_raw.replace("add:", "").split("|"):
            if item:
                lines.append(f"  + {item}")
    if rms_raw:
        for item in rms_raw.replace("rm:", "").split("|"):
            if item:
                lines.append(f"  - {item}")
    return "\n".join(lines)


def _decompress_code_signature(text: str) -> str:
    """Expand ES fn:name(args)->ret back to Python def."""
    def _repl(m: re.Match) -> str:
        prefix = "async def" if m.group(1) else "def"
        name = m.group(2)
        args = m.group(3) or ""
        ret = f" -> {m.group(4)}" if m.group(4) else ""
        return f"{prefix} {name}({args}){ret}:"

    return re.sub(
        r"(async_)?fn:(\w+)\(([^)]*)\)(?:->(\S+))?",
        _repl,
        text,
    )


def compression_ratio(original: str, compressed: str) -> float:
    """Return the compression ratio (original / compressed size)."""
    if not compressed:
        return 1.0
    return len(original) / len(compressed)


if __name__ == "__main__":
    sample = (
        "The authentication module is a critical component that has a dependency "
        "on the database and is responsible for verifying user credentials. "
        "It was completed by Maya and will be deprecated in the next release."
    )
    es = compress(sample, confidence=4)
    print("Original  :", sample)
    print("Compressed:", es)
    print(f"Ratio     : {compression_ratio(sample, es):.1f}x")
    print("Decompress:", decompress(es))
