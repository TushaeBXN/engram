"""Optional secret redaction before memories are saved.

Notes, files and conversations sometimes contain API keys, tokens or
passwords. With ``"redact_secrets": true`` in ``~/.engram/config.json``,
every drawer is passed through :func:`redact_secrets` before it is written,
so the secret never reaches disk or the search index. Matches are replaced
with ``[REDACTED:<kind>]``. Off by default, because Engram otherwise keeps
your text exactly as written.

Usage::

    redact_secrets("my key is sk-ant-api03-abc...")   # "my key is [REDACTED:api_key]"
"""

from __future__ import annotations

import re

# (kind, pattern). Specific formats first, generic "password = ..." last.
SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("api_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}")),
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]
# "password: hunter22", "api_key = '...'", "token=..." (keeps the label, hides the value)
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|passphrase|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token)"
    r"(\s*[:=]\s*[\"']?)([^\s\"']{6,})"
)


def redact_secrets(text: str) -> str:
    """*text* with recognised secrets replaced by ``[REDACTED:<kind>]``."""
    if not text:
        return text
    for kind, pattern in SECRET_PATTERNS:
        text = pattern.sub(f"[REDACTED:{kind}]", text)

    def _assignment(m: re.Match) -> str:
        if m.group(3).startswith("[REDACTED"):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}[REDACTED:{m.group(1).lower().replace('-', '_')}]"

    return _ASSIGNMENT.sub(_assignment, text)
