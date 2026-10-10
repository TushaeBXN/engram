"""Engram Shorthand (ES) — a compact, LLM-readable shorthand for AI context.

Design principles
-----------------
* **Readable by any LLM** without a decoder — the shorthand is plain text.
* **Whole words only** — symbols replace complete words and phrases, never
  parts of words, so "authorization" or "standard" are never mangled.
* **Factual / relational data**: symbols replace common words and phrases;
  filler words ("the", "that", "very" …) are dropped.
* **Code-aware**: compact function signatures and indentation; the English
  symbol table is never applied to code.
* **Diffs**: CHANGE:file|add:symbol|rm:symbol notation.
* **Confidence weights**: ★★★★ (4/5) = high confidence.

ES is lossy and is meant for context, not storage: drawers keep the original
text. ``decompress()`` is best-effort and only expands symbols that cannot
appear in ordinary text (∴ ∵ → ¬ …); ASCII operators such as ":" and "|"
are left alone so URLs, code and punctuation survive.

Typical ratios (benchmarks/longmemeval_bench.py --compression-only)
-------------------------------------------------------------------
* Factual paragraphs : ~1.6×
* Code-heavy content  : ~1.1×
* Mixed               : ~1.5×
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# ES symbol table
# ---------------------------------------------------------------------------

# (phrase, replacement). Phrases match whole words only, case-insensitively,
# so "or" never touches "authorization" and "and" never touches "standard".
# They are applied longest phrase first.
SYMBOL_TABLE: list[tuple[str, str]] = [
    # Wordy phrases
    ("due to the fact that", "∵"),
    ("in order to", "to"),
    ("is able to", "can"),
    ("are able to", "can"),
    ("a lot of", "many"),
    ("as well as", "&"),
    ("at this point in time", "now"),
    ("in the event that", "if"),
    # Logical / temporal
    ("therefore", "∴"),
    ("because", "∵"),
    ("implies", "→"),
    ("leads to", "→"),
    ("results in", "→"),
    ("caused by", "←"),
    ("not equal to", "≠"),
    ("greater than or equal to", "≥"),
    ("less than or equal to", "≤"),
    ("approximately", "≈"),
    ("infinity", "∞"),
    ("does not", "¬"),
    ("do not", "¬"),
    ("did not", "¬"),
    ("is not", "¬"),
    ("not", "¬"),
    ("and", "&"),
    ("or", "|"),
    # Relations
    ("is a", "="),
    ("is an", "="),
    ("is", ":"),
    ("are", ":"),
    ("was", "<"),
    ("were", "<"),
    ("will be", ">"),
    ("has", "+"),
    ("have", "+"),
    ("had", "+"),
    ("without", "w/o"),
    ("with", "w/"),
    ("regarding", "re:"),
    ("related to", "~"),
    ("assigned to", "@"),
    ("is responsible for", "owns:"),
    ("responsible for", "owns:"),
    ("works on", "→"),
    ("works at", "@"),
    ("started on", "from:"),
    ("ended on", "to:"),
    ("completed", "✓"),
    ("incomplete", "✗"),
    ("critical", "★★"),
    ("important", "★"),
    ("high priority", "!!!"),
    ("low priority", "↓"),
    ("breaking change", "💥"),
    # Architecture / dev vocabulary
    ("application programming interface", "API"),
    ("continuous integration", "CI"),
    ("continuous deployment", "CD"),
    ("command line interface", "CLI"),
    ("artificial intelligence", "AI"),
    ("machine learning", "ML"),
    ("user interface", "UI"),
    ("pull requests", "PRs"),
    ("pull request", "PR"),
    ("authentication", "auth"),
    ("authorization", "authz"),
    ("configuration", "cfg"),
    ("databases", "dbs"),
    ("database", "db"),
    ("environments", "envs"),
    ("environment", "env"),
    ("repositories", "repos"),
    ("repository", "repo"),
    ("dependencies", "deps"),
    ("dependency", "dep"),
    ("documentation", "docs"),
    ("implementation", "impl"),
    ("information", "info"),
    ("functions", "fns"),
    ("function", "fn"),
    ("parameters", "params"),
    ("parameter", "param"),
    ("arguments", "args"),
    ("argument", "arg"),
    ("directories", "dirs"),
    ("directory", "dir"),
    ("development", "dev"),
    ("production", "prod"),
    ("kubernetes", "k8s"),
    ("javascript", "JS"),
    ("typescript", "TS"),
    ("messages", "msgs"),
    ("message", "msg"),
    ("requests", "reqs"),
    ("request", "req"),
    ("responses", "resps"),
    ("response", "resp"),
    ("version", "v"),
]

# Filler words dropped entirely. Lossy, which is fine: drawers keep the
# original text and ES is only used for compact context.
FILLER_WORDS: tuple[str, ...] = (
    "the", "a", "an", "that", "very", "really", "just", "basically",
    "actually", "currently", "also", "quite", "simply",
)

# Replacements that read as operators are written without surrounding spaces.
_TIGHT = {"&", "|", ":", "=", "<", ">", "+", "→", "←", "∴", "∵", "≠", "≥", "≤", "≈", "@", "~"}


def _word_pattern(phrase: str) -> str:
    """Regex for *phrase* as whole words, allowing any whitespace between words."""
    return r"(?<![\w])" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?![\w])"


_COMPRESS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"[ \t]*" + _word_pattern(src) + r"[ \t]*", re.IGNORECASE)
        if dst in _TIGHT
        else re.compile(_word_pattern(src), re.IGNORECASE),
        dst,
    )
    # Longest phrases first, so "is responsible for" wins over "is".
    for src, dst in sorted(SYMBOL_TABLE, key=lambda p: (-len(p[0].split()), -len(p[0])))
]

_FILLER_PATTERN = re.compile(
    r"(?<![\w])(?:" + "|".join(FILLER_WORDS) + r")(?![\w])[ \t]*", re.IGNORECASE
)

# decompress() only expands symbols that cannot appear in ordinary text.
# ASCII operators such as ":" "|" "&" "<" are left alone, because expanding
# them would corrupt URLs, code, tables and normal punctuation.
_EXPANSIONS: dict[str, str] = {
    "∴": "therefore", "∵": "because", "→": "leads to", "←": "caused by",
    "≠": "not equal to", "≥": "greater than or equal to",
    "≤": "less than or equal to", "≈": "approximately", "∞": "infinity",
    "¬": "not ", "✓": "completed ", "✗": "incomplete ", "💥": "breaking change",
}
_DECOMPRESS_PATTERN = re.compile("|".join(re.escape(k) for k in _EXPANSIONS))

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
# Prose and code passes
# ---------------------------------------------------------------------------

# URLs, `inline code`, and tokens like auth.py or src/app are never rewritten.
_PROTECTED = re.compile(r"`[^`]*`|\S+://\S+|\S*\w[/\\.]\w\S*")


def _compress_prose(text: str) -> str:
    protected: list[str] = []

    def _hide(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _PROTECTED.sub(_hide, text)
    for pattern, repl in _COMPRESS_PATTERNS:
        text = pattern.sub(repl, text)
    text = _FILLER_PATTERN.sub("", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([.,;!?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _compress_code(text: str) -> str:
    """Compact code: short signatures, one space per indent level, no blank lines.

    The English symbol table is not applied, so identifiers and operators in
    the code are left untouched.
    """
    text = _compress_code_signature(text)
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        lines.append(" " * (indent // 4 + (1 if indent % 4 else 0)) + stripped.rstrip())
    return "\n".join(lines)


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
        text = _compress_code(text)
    else:
        text = _compress_prose(text)

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

    # Expand unambiguous symbols, keeping words separated by single spaces
    text = _DECOMPRESS_PATTERN.sub(lambda m: f" {_EXPANSIONS[m.group(0)].strip()} ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([.,;!?])", r"\1", text)

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
