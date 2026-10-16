"""Auto-recall: give Claude relevant memories before it answers.

Claude Code runs a ``UserPromptSubmit`` hook each time you send a message.
``engram-recall`` is that hook: it searches Engram for the message and, if
something is genuinely relevant, adds a short note to Claude's context with
up to a few memories (current versions first, outdated ones labelled).

It is built to stay out of the way:

* nothing is added unless a memory clears the relevance bar
  (``recall_min_relevance``, meaning similarity 0..1);
* at most ``recall_max`` memories, each trimmed, about 400 tokens in all;
* a memory already shown earlier in the same Claude session isn't repeated;
* short messages and slash commands are skipped;
* wings in ``recall_exclude_wings`` (default: the reference ``library``) are
  never shown;
* any error means no output: the hook never blocks or breaks a prompt.

Each run is logged (time, counts, milliseconds; not the prompt text) to
``~/.engram/recall.log`` so you can see whether it helps or floods.
Preview what would be recalled with ``engram recall "your message"``.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HEADER = ("[Engram memory: notes from earlier sessions that may be relevant. Use them if they "
          "help, ignore them if not. Outdated notes are history; prefer the current version.]")
MIN_PROMPT_CHARS = 12
SNIPPET_CHARS = 400
SESSION_TTL_DAYS = 7


def _cfg_value(cfg: dict, key: str, default):
    value = cfg.get(key, default)
    return default if value is None else value


def _session_file(session_id: str) -> Optional[Path]:
    from engram import config
    if not session_id:
        return None
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:80]
    return config.ENGRAM_DIR / "recall" / f"{safe}.json" if safe else None


def _seen(session_id: str) -> set:
    path = _session_file(session_id)
    try:
        return set(json.loads(path.read_text())) if path and path.exists() else set()
    except (OSError, ValueError):
        return set()


def _remember_seen(session_id: str, ids: set) -> None:
    path = _session_file(session_id)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(ids)))
        cutoff = time.time() - SESSION_TTL_DAYS * 86400
        for old in path.parent.glob("*.json"):  # tidy up old sessions
            if old.stat().st_mtime < cutoff:
                old.unlink()
    except OSError:
        pass


def _log(entry: dict) -> None:
    from engram import config
    try:
        config.ENGRAM_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.ENGRAM_DIR / "recall.log", "a") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 **entry}) + "\n")
    except OSError:
        pass


def select(results: list[dict], cfg: dict, seen: set = frozenset()) -> list[dict]:
    """The results worth showing: relevant, not excluded, not already shown."""
    min_rel = float(_cfg_value(cfg, "recall_min_relevance", 0.35))
    limit = int(_cfg_value(cfg, "recall_max", 3))
    excluded = set(_cfg_value(cfg, "recall_exclude_wings", ["library"]))
    relevant = {r["id"] for r in results if r.get("semantic_score", 0.0) >= min_rel}
    picked = []
    for r in results:
        meta = r.get("metadata") or {}
        if meta.get("wing") in excluded or r["id"] in seen:
            continue
        # A current version that search pulled in above a relevant outdated note counts too.
        if r["id"] not in relevant and r.get("via") not in relevant:
            continue
        picked.append(r)
        if len(picked) >= limit:
            break
    return picked


def format_note(picked: list[dict]) -> str:
    lines = [HEADER]
    for r in picked:
        meta = r.get("metadata") or {}
        where = "/".join(x for x in (meta.get("wing"), meta.get("room")) if x)
        when = (meta.get("timestamp") or "")[:10]
        label = ""
        if r.get("status") == "superseded":
            label = f"OUTDATED (replaced by {str(r.get('current_id', ''))[:8]}) "
        elif r.get("supersedes"):
            label = "CURRENT "
        text = " ".join(r["text"].split())
        if len(text) > SNIPPET_CHARS:
            text = text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"
        head = " · ".join(x for x in (where, when) if x)
        lines.append(f"- {label}({head}) {text} [id {r['id'][:13]}]")
    return "\n".join(lines)


def recall(prompt: str, session_id: str = "", searcher=None, cfg: Optional[dict] = None,
           remember: bool = True) -> str:
    """The note to add for *prompt* ('' when nothing relevant)."""
    from engram.config import load_config

    prompt = (prompt or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith("/"):
        return ""
    cfg = cfg if cfg is not None else load_config()
    if not _cfg_value(cfg, "recall", True):
        return ""
    if searcher is None:
        from engram.backends import backend_from_config
        from engram.chateau import Chateau
        from engram.searcher import Searcher
        searcher = Searcher(backend_from_config(cfg), Chateau(), cfg)
    limit = int(_cfg_value(cfg, "recall_max", 3))
    results = searcher.search(prompt[:2000], n=limit * 4,
                              rerank=bool(_cfg_value(cfg, "recall_rerank", False)))
    seen = _seen(session_id) if remember else set()
    picked = select(results, cfg, seen)
    if remember and picked:
        _remember_seen(session_id, seen | {r["id"] for r in picked})
    return format_note(picked) if picked else ""


def main() -> None:
    """Claude Code UserPromptSubmit hook: read the payload on stdin, print context JSON."""
    started = time.monotonic()
    shown = 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        note = recall(payload.get("prompt", ""), session_id=payload.get("session_id", ""))
        if note:
            shown = note.count("\n- ")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                     "additionalContext": note}}))
    except Exception as exc:  # never break the user's prompt
        _log({"error": type(exc).__name__})
        return
    _log({"shown": shown, "ms": int((time.monotonic() - started) * 1000)})


if __name__ == "__main__":
    main()
