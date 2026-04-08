"""Tests for engram.chateau — the château data model."""

import json
import tempfile
from pathlib import Path

import pytest

from engram.chateau import Chateau, Wing, Room, Hall, Drawer, Closet, Tunnel, HALL_TYPES


@pytest.fixture
def palace(tmp_path):
    return Chateau(chateau_path=tmp_path)


# ---------------------------------------------------------------------------
# Wing tests
# ---------------------------------------------------------------------------

def test_create_wing(palace):
    wing = palace.create_wing("myapp", description="Test wing")
    assert wing.name == "myapp"
    assert wing.description == "Test wing"
    assert (palace.path / "myapp" / "wing.json").exists()


def test_list_wings_empty(palace):
    assert palace.list_wings() == []


def test_list_wings(palace):
    palace.create_wing("wing_a")
    palace.create_wing("wing_b")
    wings = palace.list_wings()
    assert len(wings) == 2
    assert {w.name for w in wings} == {"wing_a", "wing_b"}


def test_get_wing(palace):
    palace.create_wing("myapp")
    wing = palace.get_wing("myapp")
    assert wing is not None
    assert wing.name == "myapp"


def test_get_wing_missing(palace):
    assert palace.get_wing("nonexistent") is None


def test_ensure_wing_creates_if_missing(palace):
    wing = palace.ensure_wing("newwing")
    assert wing.name == "newwing"
    assert palace.get_wing("newwing") is not None


# ---------------------------------------------------------------------------
# Room tests
# ---------------------------------------------------------------------------

def test_create_room(palace):
    room = palace.create_room("myapp", "auth-migration")
    assert room.name == "auth-migration"
    assert room.wing == "myapp"
    # All hall directories should be created
    for hall in HALL_TYPES:
        assert (palace.room_path("myapp", "auth-migration") / hall).exists()


def test_list_rooms(palace):
    palace.create_room("myapp", "room-a")
    palace.create_room("myapp", "room-b")
    rooms = palace.list_rooms("myapp")
    assert len(rooms) == 2


def test_list_rooms_empty_wing(palace):
    palace.create_wing("empty-wing")
    assert palace.list_rooms("empty-wing") == []


def test_get_room(palace):
    palace.create_room("myapp", "auth")
    room = palace.get_room("myapp", "auth")
    assert room is not None
    assert room.name == "auth"


# ---------------------------------------------------------------------------
# Drawer tests
# ---------------------------------------------------------------------------

def test_save_and_get_drawer(palace):
    drawer = Drawer(
        content="Auth module uses JWT tokens.",
        wing="myapp",
        room="auth",
        hall="facts",
    )
    palace.save_drawer(drawer)
    fetched = palace.get_drawer("myapp", "auth", "facts", drawer.id)
    assert fetched is not None
    assert fetched.content == "Auth module uses JWT tokens."
    assert fetched.id == drawer.id


def test_drawer_pinned_default_false(palace):
    drawer = Drawer(content="test", wing="w", room="r", hall="facts")
    palace.save_drawer(drawer)
    fetched = palace.get_drawer("w", "r", "facts", drawer.id)
    assert fetched.pinned is False


def test_pin_drawer(palace):
    drawer = Drawer(content="important fact", wing="w", room="r", hall="facts")
    palace.save_drawer(drawer)
    pinned = palace.pin_drawer(drawer.id)
    assert pinned is not None
    assert pinned.pinned is True
    # Confirm persistence
    fetched = palace.get_drawer("w", "r", "facts", drawer.id)
    assert fetched.pinned is True


def test_delete_drawer(palace):
    drawer = Drawer(content="to delete", wing="w", room="r", hall="facts")
    palace.save_drawer(drawer)
    ok = palace.delete_drawer("w", "r", "facts", drawer.id)
    assert ok is True
    assert palace.get_drawer("w", "r", "facts", drawer.id) is None


def test_delete_nonexistent_drawer(palace):
    assert palace.delete_drawer("w", "r", "facts", "nonexistent") is False


def test_iter_drawers_all(palace):
    for i in range(5):
        drawer = Drawer(content=f"content {i}", wing="w", room="r", hall="facts")
        palace.save_drawer(drawer)
    drawers = list(palace.iter_drawers())
    assert len(drawers) == 5


def test_iter_drawers_filter_wing(palace):
    for wing in ["w1", "w2"]:
        drawer = Drawer(content="x", wing=wing, room="r", hall="facts")
        palace.save_drawer(drawer)
    w1_drawers = list(palace.iter_drawers(wing="w1"))
    assert len(w1_drawers) == 1
    assert w1_drawers[0].wing == "w1"


def test_iter_drawers_filter_hall(palace):
    for hall in HALL_TYPES:
        drawer = Drawer(content=f"in {hall}", wing="w", room="r", hall=hall)
        palace.save_drawer(drawer)
    facts = list(palace.iter_drawers(hall="facts"))
    assert len(facts) == 1
    assert facts[0].hall == "facts"


def test_drawer_age_days(palace):
    drawer = Drawer(content="old memory", wing="w", room="r", hall="facts")
    age = drawer.age_days()
    assert age >= 0.0


# ---------------------------------------------------------------------------
# Closet tests
# ---------------------------------------------------------------------------

def test_save_and_get_closet(palace):
    closet = Closet(content="auth:JWT|db:postgres", wing="myapp", room="auth", hall="facts")
    palace.save_closet(closet)
    fetched = palace.get_closet("myapp", "auth", "facts")
    assert fetched is not None
    assert fetched.content == "auth:JWT|db:postgres"


def test_get_closet_missing(palace):
    palace.create_room("myapp", "empty-room")
    assert palace.get_closet("myapp", "empty-room", "facts") is None


# ---------------------------------------------------------------------------
# Tunnel tests
# ---------------------------------------------------------------------------

def test_add_and_list_tunnels(palace):
    palace.create_wing("wing1")
    palace.create_wing("wing2")
    t = palace.add_tunnel("shared-room", "wing1", "wing2")
    assert t.room == "shared-room"
    tunnels = palace.list_tunnels("wing1")
    assert len(tunnels) == 1
    assert tunnels[0].source_wing == "wing1"


def test_list_tunnels_empty(palace):
    palace.create_wing("lonely")
    assert palace.list_tunnels("lonely") == []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_empty(palace):
    s = palace.stats()
    assert s["wings"] == 0
    assert s["rooms"] == 0


def test_stats_with_data(palace):
    palace.create_room("w", "r")
    d = Drawer(content="test", wing="w", room="r", hall="facts")
    palace.save_drawer(d)
    s = palace.stats()
    assert s["wings"] == 1
    assert s["rooms"] == 1
    assert s["drawers"] >= 1
