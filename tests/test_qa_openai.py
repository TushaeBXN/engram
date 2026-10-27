"""engram answer with an OpenAI-compatible chat server (uzu, LM Studio, ...)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engram.qa import AnswerConfig, AnswerGenerator, LLMConfigError, llm_settings


class _Fake(BaseHTTPRequestHandler):
    calls: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append((self.path, body["model"], self.headers.get("Authorization")))
        out = json.dumps({"choices": [{"message": {"content": " Lucia [1] "}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class _Searcher:
    def search(self, question, n=5, wing=None):
        return [{"text": "We switched to Lucia.", "final_score": 0.9}]


@pytest.fixture
def server():
    _Fake.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_answer_uses_openai_server(server):
    fields = llm_settings({"llm_api_url": server + "/", "llm_api_model": "qwen", "llm_api_key": "k"})
    result = AnswerGenerator(_Searcher(), AnswerConfig(**fields)).generate("why?")
    assert result["answer"] == "Lucia [1]"
    assert _Fake.calls == [("/v1/chat/completions", "qwen", "Bearer k")]


def test_unset_means_ollama(monkeypatch):
    monkeypatch.delenv("ENGRAM_LLM_API_URL", raising=False)
    assert llm_settings({}) == {}


def test_remote_server_refused_unless_allowed():
    cfg = {"llm_api_url": "https://api.example.com/v1"}
    with pytest.raises(LLMConfigError):
        llm_settings(cfg)
    assert llm_settings({**cfg, "llm_api_allow_remote": True})["openai_api_url"] == cfg["llm_api_url"]


def test_bad_url_refused():
    with pytest.raises(LLMConfigError):
        llm_settings({"llm_api_url": "localhost:8000"})


def test_error_is_reported_not_raised():
    cfg = AnswerConfig(openai_api_url="http://127.0.0.1:1/v1")
    assert AnswerGenerator(_Searcher(), cfg).generate("x")["answer"].startswith("Error querying LLM")
