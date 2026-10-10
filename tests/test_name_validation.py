"""Tests for path-safety of wing / room / hall / drawer / agent names."""

import pytest

from engram import agents
from engram.chateau import Chateau, Drawer, InvalidNameError, validate_name


@pytest.fixture
def palace(tmp_path):
    return Chateau(chateau_path=tmp_path / "chateau")


BAD_NAMES = ["", "   ", ".", "..", "../escaped", "a/b", "a\\b", "/etc", "nul\0byte"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_validate_name_rejects_unsafe(name):
    with pytest.raises(InvalidNameError):
        validate_name(name)


@pytest.mark.parametrize("name", ["myapp", "auth-migration", "my app", "v1.2", "..hidden", "café"])
def test_validate_name_accepts_normal_names(name):
    assert validate_name(name) == name


@pytest.mark.parametrize("field", ["wing", "room", "hall"])
def test_save_drawer_rejects_traversal(palace, tmp_path, field):
    kwargs = {"content": "x", "wing": "w", "room": "r", "hall": "facts", field: "../../escaped"}
    with pytest.raises(InvalidNameError):
        palace.save_drawer(Drawer(**kwargs))
    assert not (tmp_path / "escaped").exists()


def test_save_drawer_rejects_traversal_in_id(palace, tmp_path):
    drawer = Drawer(content="x", wing="w", room="r", hall="facts")
    drawer.id = "../../../escaped"
    with pytest.raises(InvalidNameError):
        palace.save_drawer(drawer)
    assert not (tmp_path / "escaped.json").exists()


def test_delete_drawer_cannot_reach_outside(palace, tmp_path):
    victim = tmp_path / "victim.json"
    victim.write_text("{}")
    with pytest.raises(InvalidNameError):
        palace.delete_drawer("w", "r", "facts", "../../../victim")
    assert victim.exists()


def test_normal_drawer_round_trip_still_works(palace):
    drawer = Drawer(content="hello", wing="my app", room="auth-migration", hall="facts")
    path = palace.save_drawer(drawer)
    assert path.is_relative_to(palace.path)
    assert palace.get_drawer("my app", "auth-migration", "facts", drawer.id).content == "hello"
    assert palace.delete_drawer("my app", "auth-migration", "facts", drawer.id)


def test_agent_name_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(agents, "AGENTS_DIR", tmp_path / "agents")
    with pytest.raises(InvalidNameError):
        agents.AgentDiary("../../escaped")
