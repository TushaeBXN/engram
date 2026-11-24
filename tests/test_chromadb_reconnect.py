"""A long-running process whose ChromaDB handle goes stale reopens the index
instead of answering from keyword search until it is restarted."""

import pytest

chromadb = pytest.importorskip("chromadb")
from chromadb.api.shared_system_client import SharedSystemClient  # noqa: E402
from chromadb.api.types import EmbeddingFunction  # noqa: E402
from chromadb.errors import InternalError  # noqa: E402

from engram.backends import chromadb_backend  # noqa: E402


class _TinyEmbedding(EmbeddingFunction):
    """Deterministic 8-dim vectors, so the test needs no model download."""

    def __init__(self):
        pass

    def __call__(self, input):
        return [[float((sum(map(ord, t)) >> i) & 1) + 0.01 * i for i in range(8)] for t in input]

    @staticmethod
    def name():
        return "engram-test-tiny"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return _TinyEmbedding()


class _StaleCollection:
    """Stands in for a collection whose process-wide System has gone stale."""

    def __getattr__(self, name):
        def fail(*a, **k):
            raise InternalError("Error executing plan: stale segment")
        return fail


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(chromadb_backend, "_cached_default_embedding_function", lambda: _TinyEmbedding())
    monkeypatch.setattr("engram.embedding.settings", lambda cfg: None)
    b = chromadb_backend.ChromaDBBackend(collection_name="reconnect-test", persist_directory=tmp_path / "chroma")
    b.add("m1", "Brian sent a photo", {"wing": "amy"})
    yield b
    SharedSystemClient.clear_system_cache()


def test_a_stale_handle_is_reopened_and_the_search_still_answers(backend, capsys):
    old_system = SharedSystemClient._identifier_to_system[backend._client._identifier]
    backend._col = _StaleCollection()

    hits = backend.search("photo", n=3)

    assert [h["id"] for h in hits] == ["m1"]
    assert SharedSystemClient._identifier_to_system[backend._client._identifier] is not old_system
    assert "could not be read" not in capsys.readouterr().err


def test_count_and_writes_reopen_too(backend):
    backend._col = _StaleCollection()
    assert backend.count() == 1
    backend._col = _StaleCollection()
    backend.add("m2", "a second memory", {"wing": "amy"})
    backend._col = _StaleCollection()
    backend.update("m2", "a second memory, edited", {"wing": "amy"})
    backend._col = _StaleCollection()
    backend.delete("m1")
    assert backend.count() == 1


def test_an_index_that_stays_broken_falls_back_with_one_warning(backend, monkeypatch, capsys):
    monkeypatch.setattr(backend, "_connect", lambda: setattr(backend, "_col", _StaleCollection()))
    backend._col = _StaleCollection()

    assert backend.search("photo") == []
    assert backend.search("photo") == []
    assert backend.count() == 0
    err = capsys.readouterr().err
    assert err.count("could not be read") == 1
    assert "even after reopening it" in err


def test_errors_that_are_not_chromas_do_not_reopen(backend, monkeypatch):
    calls = []
    monkeypatch.setattr(backend, "_reconnect", lambda: calls.append(1) or True)

    class _Bad:
        def upsert(self, **k):
            raise ValueError("bad metadata")

    backend._col = _Bad()
    with pytest.raises(ValueError):
        backend.add("m3", "x", {})
    assert calls == []


def test_a_bad_argument_does_not_reopen(backend, monkeypatch):
    from chromadb.errors import InvalidArgumentError
    calls = []
    monkeypatch.setattr(backend, "_reconnect", lambda: calls.append(1) or True)

    class _Bad:
        def upsert(self, **k):
            raise InvalidArgumentError("bad id")

    backend._col = _Bad()
    with pytest.raises(InvalidArgumentError):
        backend.add("m3", "x", {})
    assert calls == []
