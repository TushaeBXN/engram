"""Drawers store original text; ES is only used for context."""

import json

import pytest

from engram import agents
from engram.chateau import Chateau, Drawer
from engram.convo_miner import ConvoMiner
from engram.miner import Miner
from engram.typed_memory import MemoryType, TypedMemory, TypedMemoryStore

ORIGINAL = "The authorization service is responsible for the order history: see https://x.io"


class _Backend:
    def __init__(self):
        self.added = {}

    def add(self, id, text, metadata):
        self.added[id] = text


@pytest.fixture
def palace(tmp_path):
    return Chateau(chateau_path=tmp_path / "chateau")


def test_miner_stores_original(palace, tmp_path):
    f = tmp_path / "notes.md"
    f.write_text(ORIGINAL)
    drawer = Miner(palace, _Backend(), config={}).mine(f, wing="w")[0]
    assert drawer.content == ORIGINAL and drawer.compressed is False
    assert palace.get_drawer("w", drawer.room, drawer.hall, drawer.id).content == ORIGINAL


def test_convo_miner_stores_original(palace):
    msg = {"role": "user", "text": ORIGINAL, "timestamp": None}
    assert ConvoMiner(palace, _Backend(), config={})._store_message(msg, "w", "r").content == ORIGINAL


def test_typed_memory_stores_original_with_type_and_stars(palace):
    store = TypedMemoryStore(palace, _Backend())
    mem = TypedMemory(content="Always prefer float32 on CPU because bfloat16 is slow",
                      memory_type=MemoryType.INSTRUCTION, confidence=0.95)
    drawer_id = store.add(mem, wing="w")
    drawer = next(d for d in palace.iter_drawers() if d.id == drawer_id)
    assert drawer.content == "[instruction] Always prefer float32 on CPU because bfloat16 is slow [★★★★]"


def test_diary_stores_original(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENTS_DIR", tmp_path / "agents")
    diary = agents.AgentDiary("claude")
    diary.write(ORIGINAL)
    entry = diary.read()[0]
    assert entry.content == ORIGINAL and entry.readable() == ORIGINAL


def test_legacy_diary_entry_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENTS_DIR", tmp_path / "agents")
    entry = agents.DiaryEntry.from_dict({"agent": "a", "content": "build failed ∴ rollback"})
    assert entry.compressed is True
    assert entry.readable() == "build failed therefore rollback"


def test_drawer_text_returns_original_unchanged():
    assert Drawer(content=ORIGINAL, wing="w", room="r", hall="facts").text() == ORIGINAL


def test_legacy_drawer_without_flag_loads_as_compressed(palace):
    legacy = Drawer(content="deploy failed ∴ rollback", wing="w", room="r", hall="facts").to_dict()
    del legacy["compressed"]
    path = palace.hall_path("w", "r", "facts")
    path.mkdir(parents=True)
    (path / f"{legacy['id']}.json").write_text(json.dumps(legacy))
    drawer = palace.get_drawer("w", "r", "facts", legacy["id"])
    assert drawer.compressed is True
    assert drawer.text() == "deploy failed therefore rollback"


def test_new_drawers_round_trip_flag(palace):
    d = Drawer(content=ORIGINAL, wing="w", room="r", hall="facts")
    palace.save_drawer(d)
    assert palace.get_drawer("w", "r", "facts", d.id).compressed is False
