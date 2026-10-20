"""Files that hold memories are written atomically, and damage is reported rather than hidden."""

import json
import os
import time

import pytest

from engram import fsio
from engram.audit import Auditor
from engram.chateau import Chateau, Drawer
from engram.knowledge_graph import KnowledgeGraph


def test_failed_write_leaves_the_old_file_and_no_leftovers(tmp_path, monkeypatch):
    target = tmp_path / "memory.json"
    fsio.atomic_write_text(target, "old")

    def boom(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        fsio.atomic_write_text(target, "new")
    assert target.read_text() == "old" and list(tmp_path.iterdir()) == [target]


def test_saving_a_drawer_never_exposes_a_partial_file(tmp_path, monkeypatch):
    palace = Chateau(chateau_path=tmp_path / "c")
    d = Drawer(content="original text", wing="w", room="r", hall="facts")
    palace.save_drawer(d)
    seen = []
    real_replace = os.replace

    def spy(src, dst):  # at the moment of the swap, the live file must still be complete
        seen.append(json.loads(open(dst).read())["content"])
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    d.content = "revised text " * 1000
    palace.save_drawer(d)
    assert seen == ["original text"] and palace.find_drawer(d.id).content.startswith("revised text")


def test_damaged_memory_files_are_reported_not_silently_dropped(tmp_path):
    palace = Chateau(chateau_path=tmp_path / "c")
    good = Drawer(content="fine", wing="w", room="r", hall="facts")
    bad = Drawer(content="x" * 500, wing="w", room="r", hall="facts")
    palace.save_drawer(good)
    path = palace.save_drawer(bad)
    path.write_text(path.read_text()[:120])                       # a write cut off part-way
    assert [d.id for d in palace.iter_drawers()] == [good.id]     # reading skips it ...
    assert palace.unreadable_files() == [path]                    # ... but it is not forgotten
    report = Auditor(palace, KnowledgeGraph(tmp_path / "kg.db")).run()
    assert report.unreadable_files == [str(path)] and report.to_dict()["unreadable_files"] == [str(path)]


def test_fix_clears_old_temporary_files_but_never_a_memory(tmp_path):
    palace = Chateau(chateau_path=tmp_path / "c")
    d = Drawer(content="keep me", wing="w", room="r", hall="facts")
    live = palace.save_drawer(d)
    stale = live.parent / f".{live.name}.4242.tmp"
    fresh = live.parent / f".{live.name}.4243.tmp"
    stale.write_text("{")
    fresh.write_text("{")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    auditor = Auditor(palace, KnowledgeGraph(tmp_path / "kg.db"))
    auditor.fix_safe(auditor.run())
    assert not stale.exists() and fresh.exists() and live.exists()   # a write in progress is left alone


# ---------------------------------------------------------------------------
# The wake-up note stays inside its budget and prefers what matters
# ---------------------------------------------------------------------------

def test_wake_up_note_respects_its_budget_and_prefers_pinned_then_newest(engram_home, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    from engram import layers
    from engram.lineage import Lineage

    monkeypatch.setattr(layers, "_L1_PATH", tmp_path / "l1.txt")
    palace = Chateau(chateau_path=tmp_path / "c")
    now = datetime.now(timezone.utc)

    def add(text, days_old, pinned=False):
        d = Drawer(content=text, wing="w", room="r", hall="facts", pinned=pinned,
                   timestamp=(now - timedelta(days=days_old)).isoformat())
        palace.save_drawer(d)
        return d

    add("Rule one: always run the tests before pushing to main.", 20, pinned=True)
    for i in range(30):
        add(f"Recent fact number {i}: " + "detail " * 12, i % 25)
    add("Ancient fact that is too old to qualify", 400)
    replaced = add("Outdated: we deploy on Fridays.", 1)
    Lineage(palace.path).supersede(replaced.id, add("We deploy on Tuesdays.", 0).id)
    stack = layers.LayerStack(palace, None, {})
    note = stack.rebuild_l1(budget_tokens=60)
    assert len(note) <= 60 * 4 and note.splitlines()[0].startswith("Rule one")      # pinned first, in budget
    assert "Ancient" not in note and "Fridays" not in note
    assert "Tuesdays" in stack.rebuild_l1(budget_tokens=2000, n=100)             # current replaces outdated
    huge = add("x" * 5000 + " end", 0, pinned=True)
    assert len(stack.rebuild_l1(budget_tokens=30)) <= 120 and huge                   # one oversized fact is cut
