"""The Python API that apps build on (for example the Amy companion's
engram_bridge.py). These calls and return shapes must keep working; change
this file only together with a CHANGELOG note for app authors."""

import json

from engram.agents import AgentDiary
from engram.backends import get_backend
from engram.chateau import Chateau, Drawer
from engram.config import IDENTITY_PATH, ensure_engram_dir  # noqa: F401  (import must work)
from engram.knowledge_graph import KnowledgeGraph
from engram.layers import LayerStack
from engram.searcher import Searcher


def test_app_memory_round_trip(engram_home):
    ensure_engram_dir()
    palace = Chateau()
    searcher = Searcher(get_backend("sqlitevec", db_path=engram_home / "vec.db"), palace)
    layers = LayerStack(palace, searcher)

    # L0 identity and wake-up context
    layers.set_identity("I am Amy, a companion.")
    assert "I am Amy" in layers.l0()
    assert isinstance(layers.l1(), str)
    layers.rebuild_l1(wing="amy")

    # Store a drawer the way an app does: save it, then add it to the backend directly
    drawer = Drawer(content="Brian prefers jazz in the evening", wing="amy", room="music",
                    hall="facts", pinned=True)
    palace.save_drawer(drawer)
    searcher.backend.add(id=drawer.id, text=drawer.content,
                         metadata={"wing": "amy", "room": "music", "hall": "facts",
                                   "timestamp": drawer.timestamp, "pinned": True})
    assert [d.id for d in palace.iter_drawers(wing="amy", room="music", hall="facts")] == [drawer.id]

    # Search with the default config: same keys apps read
    hits = searcher.search("what music does Brian like", n=8, wing="amy")
    assert hits and hits[0]["id"] == drawer.id
    assert {"text", "final_score", "metadata"} <= set(hits[0])
    assert "rerank_score" not in hits[0]  # the reranker stays off unless enabled
    json.dumps(hits)  # results must stay JSON-serialisable


def test_app_diary_and_knowledge_graph(engram_home):
    diary = AgentDiary("amy")
    diary.write("Helped Brian plan the week", tags=["planning"])
    entries = diary.read(last_n=5)
    assert entries[-1].timestamp[:4].isdigit()
    assert "plan the week" in entries[-1].readable()

    kg = KnowledgeGraph()
    kg.add(subject="Amy", predicate="knows", obj="Brian", confidence=1.0)
    triples = kg.query(entity="Amy", predicate=None)
    assert [(t.subject, t.predicate, t.object, t.confidence) for t in triples] == \
        [("Amy", "knows", "Brian", 1.0)]
