"""Engram MCP Server — 31 tools for Claude, Cursor, VS Code, Gemini, Codex and any MCP client.

Implements the Model Context Protocol over stdio.  Start with::

    python -m engram.mcp_server

All tools are prefixed ``engram_``.

Tool list (31):
    1.  engram_search          — semantic search
    2.  engram_add_memory      — store a new drawer
    3.  engram_wake_up         — return L0+L1 context
    4.  engram_load_room       — return L2 room context
    5.  engram_compress        — ES compress text
    6.  engram_decompress      — ES decompress text
    7.  engram_kg_query        — KG entity lookup
    8.  engram_kg_add          — add KG triple
    9.  engram_kg_invalidate   — invalidate KG triple
    10. engram_kg_timeline     — chronological entity timeline
    11. engram_list_wings      — list all wings
    12. engram_list_rooms      — list rooms in a wing
    13. engram_get_drawer      — fetch a specific drawer
    14. engram_delete_drawer   — delete a drawer
    15. engram_create_wing     — create a new wing
    16. engram_create_room     — create a new room
    17. engram_diary_write     — write agent diary entry
    18. engram_diary_read      — read agent diary
    19. engram_status          — château stats
    20. engram_audit           — health audit (NEW)
    21. engram_replay          — session replay (NEW)
    22. engram_pin             — pin a drawer
    23. engram_correct         — save a correction that replaces a memory
    24. engram_supersede       — mark one stored memory as replacing another
    25. engram_dispute         — mark two memories as conflicting, undecided
    26. engram_history         — a memory's status and replacement history
    27. engram_recall          — the few memories clearly relevant to a message (auto-recall)
    28. engram_link            — based_on / derived_from / contradicts / supersedes between memories
    29. engram_source          — record where a memory came from
    30. engram_why             — explain a memory: source, evidence, history, conflicts, relevance
    31. engram_check           — what needs review: corrected evidence, unsupported inferences, conflicts

On connect, the server also sends ``instructions`` (MCP InitializeResult) so
clients that pass them to the model know to check memory first.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from engram import __version__
from engram.validate import ArgumentError

# ---------------------------------------------------------------------------
# MCP protocol helpers (minimal stdio JSON-RPC implementation)
# ---------------------------------------------------------------------------

def _send(obj: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def _result(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

# Sent to every client on connect; clients that support it show it to the model.
INSTRUCTIONS = (
    "Engram is this user's long-term memory, kept on their own computer. "
    "Before answering a request that may depend on earlier work, decisions, preferences, people or "
    "projects, call engram_recall with the user's message (and the project folder, if you know it); "
    "it returns only clearly relevant memories, or says nothing matched. "
    "When the user makes a decision or states a lasting fact or preference, save it with "
    "engram_add_memory. When something changed, call engram_correct on the old memory instead of "
    "adding a contradicting one. Memories marked OUTDATED are history: use the current version. "
    "Say where a memory came from with 'source' (user, primary, secondary, tool, inference) and, when "
    "you save a conclusion, link it to the memories it rests on with 'based_on'. When asked why you "
    "believe something, or before relying on a conclusion, call engram_why: it shows the evidence, "
    "whether that evidence has since been corrected, and what is inference rather than record."
)

_SOURCE_PROPS = {
    "source": {"type": "string", "enum": ["user", "primary", "secondary", "tool", "inference"],
               "description": ("Where it came from: user (the person said it), primary (original "
                               "document, law, ruling, data), secondary (reporting or analysis), "
                               "tool (search or program output), inference (your own conclusion)")},
    "source_ref": {"type": "string", "description": "Citation, URL or document it came from"},
}

TOOLS: list[dict] = [
    {
        "name": "engram_search",
        "description": "Semantic search across the château. Returns ranked results with recency weighting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "n": {"type": "integer", "default": 10},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "no_decay": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "engram_add_memory",
        "description": ("Store a new memory drawer in the château. The result lists "
                        "'possible_updates': existing memories this one may replace. If it "
                        "does, call engram_supersede (or pass 'supersedes' here)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory content to store"},
                "wing": {"type": "string", "default": "default"},
                "room": {"type": "string", "default": "general"},
                "hall": {"type": "string", "default": "facts", "enum": ["facts", "events", "discoveries", "preferences", "advice"]},
                "pinned": {"type": "boolean", "default": False},
                "supersedes": {"type": "string", "description": "ID of a memory this one replaces (optional)"},
                "reason": {"type": "string", "description": "Why it replaces it (used with 'supersedes')"},
                **_SOURCE_PROPS,
                "based_on": {"type": "array", "items": {"type": "string"},
                             "description": "IDs of memories that are evidence for this one"},
                "derived_from": {"type": "array", "items": {"type": "string"},
                                 "description": "IDs of memories this one was inferred from"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "engram_wake_up",
        "description": "Return L0+L1 cold-start context (~170 tokens). Load this at the start of every session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "rebuild_l1": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "engram_load_room",
        "description": "Return L2 context for a specific room (ES-compressed closets for all halls).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "room": {"type": "string"},
            },
            "required": ["wing", "room"],
        },
    },
    {
        "name": "engram_compress",
        "description": "Compress text into Engram Shorthand (ES).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "is_code": {"type": "boolean", "default": False},
                "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["text"],
        },
    },
    {
        "name": "engram_decompress",
        "description": "Decompress Engram Shorthand (ES) back to natural language.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "engram_kg_query",
        "description": "Query the temporal knowledge graph for an entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string"},
                "predicate": {"type": "string"},
                "active_only": {"type": "boolean", "default": True},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "engram_kg_add",
        "description": "Add a triple to the knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "valid_from": {"type": "string"},
                "valid_until": {"type": "string"},
                "confidence": {"type": "number", "default": 1.0},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "engram_kg_invalidate",
        "description": "Invalidate (end) a KG triple.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "ended": {"type": "string"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "engram_kg_timeline",
        "description": "Return chronological timeline of all triples for an entity.",
        "inputSchema": {
            "type": "object",
            "properties": {"entity": {"type": "string"}},
            "required": ["entity"],
        },
    },
    {
        "name": "engram_list_wings",
        "description": "List all wings in the château.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "engram_list_rooms",
        "description": "List all rooms in a wing.",
        "inputSchema": {
            "type": "object",
            "properties": {"wing": {"type": "string"}},
            "required": ["wing"],
        },
    },
    {
        "name": "engram_get_drawer",
        "description": "Fetch a specific drawer by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string"},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "hall": {"type": "string"},
            },
            "required": ["drawer_id"],
        },
    },
    {
        "name": "engram_delete_drawer",
        "description": "Delete a drawer from the château.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "hall": {"type": "string"},
                "drawer_id": {"type": "string"},
            },
            "required": ["wing", "room", "hall", "drawer_id"],
        },
    },
    {
        "name": "engram_create_wing",
        "description": "Create a new wing in the château.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "engram_create_room",
        "description": "Create a new room within a wing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["wing", "name"],
        },
    },
    {
        "name": "engram_diary_write",
        "description": "Write a diary entry for a specialist agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "entry": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["agent", "entry"],
        },
    },
    {
        "name": "engram_diary_read",
        "description": "Read recent diary entries for a specialist agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "last_n": {"type": "integer", "default": 10},
            },
            "required": ["agent"],
        },
    },
    {
        "name": "engram_status",
        "description": "Return château statistics (wings, rooms, drawers, closets).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "engram_audit",
        "description": "Run a memory health audit. Returns JSON summary of issues found.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fix": {"type": "boolean", "default": False, "description": "Auto-resolve safe issues."},
            },
        },
    },
    {
        "name": "engram_replay",
        "description": "Return the chronological story of a room (session replay).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room": {"type": "string"},
                "wing": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "format": {"type": "string", "enum": ["text", "json"], "default": "text"},
            },
            "required": ["room"],
        },
    },
    {
        "name": "engram_pin",
        "description": "Pin a drawer so it bypasses recency decay.",
        "inputSchema": {
            "type": "object",
            "properties": {"drawer_id": {"type": "string"}},
            "required": ["drawer_id"],
        },
    },
    {
        "name": "engram_recall",
        "description": ("The few memories clearly relevant to a message, current versions first, or a "
                        "note that nothing matched. Call it before answering anything that may depend "
                        "on past work, decisions or preferences."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The user's message or the task at hand"},
                "cwd": {"type": "string", "description": "Project folder, if known (its memories come first)"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "engram_correct",
        "description": ("Save a correction: a new memory that replaces an outdated one (same "
                        "wing/room/hall). The old memory stays searchable but is marked "
                        "superseded, and search shows the correction first. Safe to retry."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "ID (or unique prefix) of the outdated memory"},
                "content": {"type": "string", "description": "The corrected, current information"},
                "reason": {"type": "string", "description": "Why it changed"},
                **_SOURCE_PROPS,
                "based_on": {"type": "array", "items": {"type": "string"},
                             "description": "IDs of memories that support the corrected version"},
            },
            "required": ["memory_id", "content"],
        },
    },
    {
        "name": "engram_supersede",
        "description": ("Record that one stored memory replaces another (e.g. 'we moved to "
                        "PostgreSQL' replaces 'we use SQLite'). Set undo=true to make the old "
                        "memory current again. Safe to retry."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_id": {"type": "string", "description": "ID of the outdated memory"},
                "new_id": {"type": "string", "description": "ID of the memory that replaces it"},
                "reason": {"type": "string"},
                "undo": {"type": "boolean", "default": False},
            },
            "required": ["old_id"],
        },
    },
    {
        "name": "engram_dispute",
        "description": "Mark two memories as conflicting when it is not yet clear which is right.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id_a": {"type": "string"},
                "id_b": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["id_a", "id_b"],
        },
    },
    {
        "name": "engram_history",
        "description": ("A memory's status (current, superseded or disputed), what replaced it, "
                        "what it replaced, when and why."),
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "engram_link",
        "description": ("Record how two stored memories relate: 'memory_id <relation> target_id'. "
                        "based_on: target is evidence for memory. derived_from: memory was inferred "
                        "from target. contradicts: they conflict, undecided. supersedes: memory "
                        "replaces target. undo=true removes the link. Safe to retry."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "relation": {"type": "string", "enum": ["based_on", "derived_from", "contradicts", "supersedes"]},
                "target_id": {"type": "string"},
                "reason": {"type": "string"},
                "undo": {"type": "boolean", "default": False},
            },
            "required": ["memory_id", "relation", "target_id"],
        },
    },
    {
        "name": "engram_source",
        "description": "Record where a stored memory came from (and optionally the citation or URL).",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}, **_SOURCE_PROPS},
            "required": ["memory_id", "source"],
        },
    },
    {
        "name": "engram_why",
        "description": ("Explain a memory: where it came from, when, whether it is record or "
                        "inference, the evidence it rests on (and whether that evidence was since "
                        "corrected or disputed), earlier versions and their evidence, conflicts, "
                        "and, given the query, why search ranked it. Use it before relying on a "
                        "conclusion or when asked to justify one."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "query": {"type": "string", "description": "The question it was retrieved for (optional)"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "engram_check",
        "description": ("Memory maintenance report: conclusions whose evidence was corrected or "
                        "disputed, inferences with no evidence, unresolved conflicts, broken "
                        "links. Changes nothing."),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_SCHEMAS: dict[str, dict] = {t["name"]: t["inputSchema"] for t in TOOLS}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

class EngramMCPServer:
    """Stateful MCP server — initialised once, tools share state."""

    def __init__(self) -> None:
        from engram.backends import backend_from_config
        from engram.chateau import Chateau
        from engram.config import load_config
        from engram.knowledge_graph import KnowledgeGraph
        from engram.layers import LayerStack
        from engram.searcher import Searcher

        self.cfg = load_config()
        self.palace = Chateau()
        self.backend = backend_from_config(self.cfg)
        self.searcher = Searcher(self.backend, self.palace, self.cfg)
        self.stack = LayerStack(self.palace, self.searcher, self.cfg)
        self.kg = KnowledgeGraph()

    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict) -> Any:
        from engram.validate import validate_arguments
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        return handler(**validate_arguments(TOOL_SCHEMAS[name], args))

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_engram_search(self, query, n=10, wing=None, room=None, no_decay=False):
        return self.searcher.search(query, n=n, wing=wing, room=room, no_decay=no_decay)

    def _tool_engram_add_memory(self, content, wing="default", room="general", hall="facts", pinned=False,
                                supersedes=None, reason="", source="", source_ref="", based_on=None,
                                derived_from=None):
        from engram.chateau import Drawer
        from engram.indexing import index_drawer
        from engram.lineage import possible_updates, supersede_memory
        from engram.relations import attach_evidence, check_source, resolve_evidence
        # Check everything that could be refused before saving anything.
        if supersedes:
            self.palace.find_drawer(supersedes) or self._missing(supersedes)
        evidence = resolve_evidence(self.palace, based_on, derived_from)
        drawer = Drawer(content=content, wing=wing, room=room, hall=hall, pinned=pinned,
                        source=check_source(source), source_ref=source_ref)
        self.palace.save_drawer(drawer)
        index_drawer(self.backend, drawer.id, drawer.content, {
            "wing": wing, "room": room, "hall": hall,
            "timestamp": drawer.timestamp, "pinned": pinned,
        })
        result = drawer.to_dict()
        if supersedes:
            try:
                result["supersedes"] = supersede_memory(self.palace, supersedes, drawer.id,
                                                        reason=reason, by="mcp")["link"]
            except Exception:  # all or nothing: drop the new memory again
                from engram.indexing import unindex_drawer
                unindex_drawer(self.backend, drawer.id)
                self.palace.delete_drawer(wing, room, hall, drawer.id)
                raise
        else:
            result["possible_updates"] = possible_updates(self.backend, self.palace, drawer)
        if evidence:
            result["evidence"] = attach_evidence(self.palace, drawer.id, evidence, by="mcp")
        return result

    @staticmethod
    def _missing(memory_id):
        from engram.lineage import LineageError
        raise LineageError(f"no memory with ID {memory_id!r}")

    def _tool_engram_recall(self, message, cwd=None):
        from engram.recall import recall
        # Asked for explicitly, so it works even when the Claude Code hook is switched off.
        note = recall(message, searcher=self.searcher, cfg={**self.cfg, "recall": True},
                      remember=False, cwd=cwd)
        return note or "Nothing in memory is clearly relevant to this."

    def _tool_engram_correct(self, memory_id, content, reason="", source="", source_ref="", based_on=None):
        from engram.lineage import correct_memory
        from engram.relations import attach_evidence, check_source, resolve_evidence
        evidence = resolve_evidence(self.palace, based_on)
        result = correct_memory(self.palace, self.backend, memory_id, content, reason=reason, by="mcp",
                                source=check_source(source), source_ref=source_ref)
        if evidence:
            result["evidence"] = attach_evidence(self.palace, result["new"]["id"], evidence, by="mcp")
        return result

    def _tool_engram_link(self, memory_id, relation, target_id, reason="", undo=False):
        from engram.relations import link_memories
        return link_memories(self.palace, memory_id, relation, target_id, reason=reason, by="mcp", undo=undo)

    def _tool_engram_source(self, memory_id, source, source_ref=""):
        from engram.relations import set_source
        return set_source(self.palace, memory_id, source, source_ref)

    def _tool_engram_why(self, memory_id, query=None):
        from engram.relations import explain
        return explain(self.palace, memory_id, query=query, searcher=self.searcher)

    def _tool_engram_check(self):
        from engram.relations import check
        return check(self.palace)

    def _tool_engram_supersede(self, old_id, new_id=None, reason="", undo=False):
        from engram.lineage import Lineage, LineageError, supersede_memory
        if undo:
            drawer = self.palace.find_drawer(old_id) or self._missing(old_id)
            return {"restored": Lineage(self.palace.path).restore(drawer.id), "id": drawer.id}
        if not new_id:
            raise LineageError("new_id is required unless undo is true")
        return supersede_memory(self.palace, old_id, new_id, reason=reason, by="mcp")

    def _tool_engram_dispute(self, id_a, id_b, reason=""):
        from engram.lineage import Lineage
        a = self.palace.find_drawer(id_a) or self._missing(id_a)
        b = self.palace.find_drawer(id_b) or self._missing(id_b)
        link, created = Lineage(self.palace.path).dispute(a.id, b.id, reason=reason, by="mcp")
        return {"link": link, "created": created}

    def _tool_engram_history(self, memory_id):
        from engram.lineage import memory_history
        return memory_history(self.palace, memory_id)

    def _tool_engram_wake_up(self, wing=None, rebuild_l1=False):
        return self.stack.wake_up(wing=wing, rebuild_l1=rebuild_l1)

    def _tool_engram_load_room(self, wing, room):
        return self.stack.load_room(wing, room)

    def _tool_engram_compress(self, text, is_code=False, confidence=None):
        from engram.shorthand import compress
        return compress(text, is_code=is_code, confidence=confidence)

    def _tool_engram_decompress(self, text):
        from engram.shorthand import decompress
        return decompress(text)

    def _tool_engram_kg_query(self, entity, predicate=None, active_only=True):
        from datetime import datetime, timezone
        at = datetime.now(timezone.utc).isoformat() if active_only else None
        triples = self.kg.query(entity, predicate=predicate, active_at=at)
        return [t.to_dict() for t in triples]

    def _tool_engram_kg_add(self, subject, predicate, object, valid_from=None, valid_until=None, confidence=1.0):
        t = self.kg.add(subject, predicate, object, valid_from=valid_from,
                        valid_until=valid_until, confidence=confidence, source="mcp")
        return t.to_dict()

    def _tool_engram_kg_invalidate(self, subject, predicate, object, ended=None):
        count = self.kg.invalidate(subject, predicate, object, ended=ended)
        return {"invalidated": count}

    def _tool_engram_kg_timeline(self, entity):
        return [t.to_dict() for t in self.kg.timeline(entity)]

    def _tool_engram_list_wings(self):
        return [w.to_dict() for w in self.palace.list_wings()]

    def _tool_engram_list_rooms(self, wing):
        return [r.to_dict() for r in self.palace.list_rooms(wing)]

    def _tool_engram_get_drawer(self, drawer_id, wing=None, room=None, hall=None):
        for drawer in self.palace.iter_drawers(wing=wing, room=room, hall=hall):
            if drawer.id == drawer_id:
                return drawer.to_dict()
        return None

    def _tool_engram_delete_drawer(self, wing, room, hall, drawer_id):
        from engram.indexing import unindex_drawer
        ok = self.palace.delete_drawer(wing, room, hall, drawer_id)
        if ok:
            unindex_drawer(self.backend, drawer_id)
        return {"deleted": ok}

    def _tool_engram_create_wing(self, name, description=""):
        w = self.palace.create_wing(name, description=description)
        return w.to_dict()

    def _tool_engram_create_room(self, wing, name, description=""):
        r = self.palace.create_room(wing, name, description=description)
        return r.to_dict()

    def _tool_engram_diary_write(self, agent, entry, tags=None):
        from engram.agents import engram_diary_write
        return engram_diary_write(agent, entry, tags=tags)

    def _tool_engram_diary_read(self, agent, last_n=10):
        from engram.agents import engram_diary_read
        return engram_diary_read(agent, last_n=last_n)

    def _tool_engram_status(self):
        return self.palace.stats()

    def _tool_engram_audit(self, fix=False):
        from engram.audit import Auditor
        auditor = Auditor(self.palace, self.kg)
        report = auditor.run()
        if fix:
            auditor.fix_safe(report)
        return report.to_dict()

    def _tool_engram_replay(self, room, wing=None, limit=50, format="text"):
        from engram.replay import Replayer
        replayer = Replayer(self.palace)
        if format == "json":
            return replayer.replay_json(room, wing=wing, limit=limit)
        return replayer.replay(room, wing=wing, limit=limit)

    def _tool_engram_pin(self, drawer_id):
        from engram.indexing import index_drawer
        drawer = self.palace.pin_drawer(drawer_id)
        if drawer:
            # Re-index so the pinned flag reaches the vector backend
            index_drawer(
                self.backend, drawer.id, drawer.content,
                {"wing": drawer.wing, "room": drawer.room, "hall": drawer.hall,
                 "timestamp": drawer.timestamp, "pinned": True},
            )
            return {"pinned": True, "drawer": drawer.to_dict()}
        return {"pinned": False, "error": f"Drawer {drawer_id} not found"}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _handle_message(server: EngramMCPServer, msg: dict) -> dict | None:
    method = msg.get("method", "")
    id_ = msg.get("id")

    if method == "initialize":
        return _result(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "engram", "version": __version__},
            "instructions": INSTRUCTIONS,
        })

    if method == "tools/list":
        return _result(id_, {"tools": TOOLS})

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            result = server.dispatch(tool_name, arguments)
            return _result(id_, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]
            })
        except ArgumentError as exc:
            return _error(id_, -32602, f"Invalid arguments for {tool_name}: {exc}")
        except Exception as exc:
            return _error(id_, -32603, f"{type(exc).__name__}: {exc}")

    if method == "notifications/initialized":
        return None  # no response for notifications

    if id_ is not None:
        return _error(id_, -32601, f"Method not found: {method}")
    return None


def run_server() -> None:
    """Start the MCP server, reading JSON-RPC from stdin."""
    server = EngramMCPServer()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _send(_error(None, -32700, f"Parse error: {e}"))
            continue
        try:
            response = _handle_message(server, msg)
            if response is not None:
                _send(response)
        except Exception:
            _send(_error(msg.get("id"), -32603, traceback.format_exc()))


if __name__ == "__main__":
    run_server()
