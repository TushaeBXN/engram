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
* a saved preference needs only ``recall_preference_min_relevance`` (0.20), because a question
  asking for a choice rarely repeats the words of the preference it should find;
* project-aware: memories from the project you're working in (Claude Code
  sends its folder) come first; other projects' memories must clear the
  higher ``recall_other_min_relevance`` bar;
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


NEUTRAL_WINGS = ("default",)  # memories saved before project wings existed


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.")[:60]


def project_wing(cwd: Optional[str], cfg: Optional[dict] = None) -> Optional[str]:
    """The wing for work in folder *cwd*: an explicit ``projects`` mapping in the
    config ({"~/code/app": "myapp"}, longest match wins), else the git
    repository's folder name, else the folder's own name. None for the home
    folder, the filesystem root, or no folder."""
    if not cwd:
        return None
    if cfg is None:
        from engram.config import load_config
        cfg = load_config()
    try:
        path = Path(cwd).expanduser().resolve()
    except OSError:
        return None
    mapping = cfg.get("projects") or {}
    best = None
    for folder, wing in mapping.items():
        try:
            root = Path(folder).expanduser().resolve()
        except OSError:
            continue
        if (path == root or root in path.parents) and (best is None or len(str(root)) > len(str(best[0]))):
            best = (root, wing)
    if best:
        return _slug(str(best[1])) or None
    if path == Path.home().resolve() or path == Path(path.anchor):
        return None
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            if folder == Path.home().resolve():
                break
            return _slug(folder.name) or None
    return _slug(path.name) or None


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


def select(results: list[dict], cfg: dict, seen: set = frozenset(),
           project: Optional[str] = None) -> list[dict]:
    """The results worth showing: relevant, not excluded, not already shown.

    With a *project*, its memories (and neutral "default" ones) need
    ``recall_min_relevance`` (preferences: ``recall_preference_min_relevance``, lower);
    other projects' need ``recall_other_min_relevance``.
    """
    min_rel = float(_cfg_value(cfg, "recall_min_relevance", 0.30))
    other_rel = float(_cfg_value(cfg, "recall_other_min_relevance", 0.55))
    limit = int(_cfg_value(cfg, "recall_max", 3))
    excluded = set(_cfg_value(cfg, "recall_exclude_wings", ["library"]))

    pref_rel = float(_cfg_value(cfg, "recall_preference_min_relevance", 0.20))

    def bar(r: dict) -> float:
        meta = r.get("metadata") or {}
        wing = meta.get("wing")
        if project is None or wing == project or wing in NEUTRAL_WINGS:
            # A saved preference is there to be used when you ask for a choice ("where should I get
            # pastries?" -> "favorite bakery"), and such a question rarely repeats its words, so it
            # gets a lower bar than facts do.
            return min(min_rel, pref_rel) if meta.get("hall") == "preferences" else min_rel
        return other_rel

    relevant = {r["id"] for r in results if r.get("semantic_score", 0.0) >= bar(r)}
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


PREVIOUS_CHARS = 140


def _previous(r: dict, palace, shown: set) -> str:
    """For a corrected memory: what it replaced, when and why, so "what was it before?" and
    "why did it change?" are answered by the note itself. Empty when the replaced memory is
    already in the note (no repeating it) or can't be read."""
    if palace is None or not r.get("supersedes"):
        return ""
    try:
        from engram.lineage import Lineage
        links = [lk for lk in Lineage(palace.path).links()
                 if lk["kind"] == "supersedes" and lk["new"] == r["id"] and lk["old"] not in shown]
        if not links:
            return ""
        link = links[-1]
        old = palace.find_drawer(link["old"])
    except (OSError, ValueError, LookupError):
        return ""
    if old is None:
        return ""
    text = " ".join(old.text().split())
    if len(text) > PREVIOUS_CHARS:
        text = text[:PREVIOUS_CHARS].rsplit(" ", 1)[0] + " …"
    why = f": {' '.join(link['reason'].split())[:100]}" if link.get("reason") else ""
    return f' (before, until {link["at"][:10]}{why}: "{text}")'


def format_note(picked: list[dict], palace=None) -> str:
    lines = [HEADER]
    shown = {r["id"] for r in picked}
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
        lines.append(f"- {label}({head}) {text} [id {r['id'][:13]}]{_previous(r, palace, shown)}")
    return "\n".join(lines)


def recall(prompt: str, session_id: str = "", searcher=None, cfg: Optional[dict] = None,
           remember: bool = True, cwd: Optional[str] = None) -> str:
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
    rerank = bool(_cfg_value(cfg, "recall_rerank", False))
    project = project_wing(cwd, cfg)
    results = []
    if project:  # the project's own memories first, so other projects can't crowd them out
        results = searcher.search(prompt[:2000], n=limit * 4, wing=project, rerank=rerank)
    have = {r["id"] for r in results}
    results += [r for r in searcher.search(prompt[:2000], n=limit * 4, rerank=rerank) if r["id"] not in have]
    seen = _seen(session_id) if remember else set()
    picked = select(results, cfg, seen, project)
    if remember and picked:
        _remember_seen(session_id, seen | {r["id"] for r in picked})
    return format_note(picked, palace=getattr(searcher, "palace", None)) if picked else ""


def main() -> None:
    """Claude Code UserPromptSubmit hook: read the payload on stdin, print context JSON."""
    started = time.monotonic()
    shown = 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        note = recall(payload.get("prompt", ""), session_id=payload.get("session_id", ""),
                      cwd=payload.get("cwd") or None)
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
