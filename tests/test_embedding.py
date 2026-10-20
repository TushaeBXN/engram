"""Using an embedding server (LM Studio, Ollama, ...) instead of the built-in model."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from typer.testing import CliRunner

from engram import config, embedding
from engram.cli import app
from engram.embedding import EmbeddingConfigError


class _Fake(BaseHTTPRequestHandler):
    calls: list = []
    fail = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append((self.path, body["model"], self.headers.get("Authorization"), len(body["input"])))
        if type(self).fail:
            self.send_response(500)
            self.end_headers()
            return
        rows = []
        for i, text in reversed(list(enumerate(body["input"]))):   # out of order on purpose
            t = text.lower()
            rows.append({"index": i, "embedding": [t.count("cat") + 0.1, t.count("dog") + 0.1, 1.0]})
        out = json.dumps({"data": rows}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_server():
    _Fake.calls, _Fake.fail = [], False
    httpd = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()
    httpd.server_close()


def test_settings_only_accept_local_servers_unless_told_otherwise():
    assert embedding.settings({}) is None
    assert embedding.settings({"embedding_api_url": "http://localhost:1234/v1", "embedding_api_model": "m"})["model"] == "m"
    assert embedding.settings({"embedding_api_url": "http://192.168.1.20/v1", "embedding_api_model": "m"})
    assert embedding.settings({"embedding_api_url": "http://studio.local/v1", "embedding_api_model": "m"})
    with pytest.raises(EmbeddingConfigError, match="would be sent there"):
        embedding.settings({"embedding_api_url": "https://api.example.com/v1", "embedding_api_model": "m"})
    assert embedding.settings({"embedding_api_url": "https://api.example.com/v1", "embedding_api_model": "m",
                               "embedding_api_allow_remote": True})
    with pytest.raises(EmbeddingConfigError, match="embedding_api_model"):
        embedding.settings({"embedding_api_url": "http://localhost:1/v1"})
    with pytest.raises(EmbeddingConfigError, match="http"):
        embedding.settings({"embedding_api_url": "file:///etc/passwd", "embedding_api_model": "m"})


def test_embed_keeps_order_batches_and_sends_the_key_only_to_that_server(fake_server):
    s = {"url": fake_server, "model": "tiny", "key": "k-123"}
    texts = [f"cat {i}" if i % 2 else f"dog {i}" for i in range(70)]
    vecs = embedding.embed(s, texts)
    assert len(vecs) == 70 and vecs[1][0] > vecs[1][1] and vecs[2][1] > vecs[2][0]   # order preserved
    assert [c[3] for c in _Fake.calls] == [32, 32, 6] and {c[2] for c in _Fake.calls} == {"Bearer k-123"}
    assert _Fake.calls[0][:2] == ("/v1/embeddings", "tiny")


def test_errors_say_what_is_wrong(fake_server):
    _Fake.fail = True
    with pytest.raises(EmbeddingConfigError, match="answered 500"):
        embedding.embed({"url": fake_server, "model": "m"}, ["x"])
    with pytest.raises(EmbeddingConfigError, match="could not reach"):
        embedding.embed({"url": "http://127.0.0.1:9/v1", "model": "m"}, ["x"])


def test_search_with_an_embedding_server_and_reindex(engram_home, fake_server, monkeypatch):
    pytest.importorskip("chromadb")
    from engram.backends import backend_from_config
    from engram.chateau import Chateau, Drawer

    monkeypatch.delenv("ENGRAM_VECTOR_BACKEND", raising=False)
    config.save_config({**config.load_config(), "vector_backend": "chromadb", "keyword_search": False})
    palace = Chateau()
    for text in ("The cat sat on the mat.", "The dog chased the ball.", "Cats and cats and cats."):
        palace.save_drawer(Drawer(content=text, wing="pets", room="r", hall="facts"))
    cfg = {**config.load_config(), "embedding_api_url": fake_server, "embedding_api_model": "tiny"}
    config.save_config(cfg)

    res = CliRunner().invoke(app, ["reindex"])
    assert res.exit_code == 0 and "tiny" in res.output and "Indexed" in res.output
    backend = backend_from_config(config.load_config())
    assert backend._collection_name.startswith("engram_drawers__")   # its own index, not the default one
    hits = backend.search("cat", n=3)
    assert hits and "cat" in hits[0]["text"].lower()
    assert backend.count() >= 3

    # Changing the model uses a fresh index and leaves this one alone.
    config.save_config({**cfg, "embedding_api_model": "tiny-2"})
    other = backend_from_config(config.load_config())
    assert other.count() == 0 and other._collection_name != backend._collection_name

    # A server that is down is an error, not "no results".
    _Fake.fail = True
    config.save_config(cfg)
    with pytest.raises(EmbeddingConfigError):
        backend_from_config(config.load_config()).search("cat", n=3)
