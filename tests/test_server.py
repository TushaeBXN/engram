"""engram serve: the local HTTP interface, and its refusals."""

import http.client
import json
import threading

import pytest
from typer.testing import CliRunner

from engram import server as srv
from engram.cli import app


def _start(engram_home, token=None, **kw):
    httpd = srv.make_server("127.0.0.1", 0, token, **kw)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _req(httpd, method, path, body=None, headers=None, host=None, declared_length=None):
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        conn.putheader(k, v)
    conn.putheader("Content-Length", str(len(data or b"") if declared_length is None else declared_length))
    conn.endheaders(data)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, (json.loads(raw) if raw else None), resp


@pytest.fixture
def httpd(engram_home):
    server = _start(engram_home)
    yield server
    server.shutdown()
    server.server_close()


def test_tools_work_over_http_with_the_same_rules_as_mcp(httpd):
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_add_memory",
                           {"content": "The database is SQLite.", "wing": "app", "room": "db"})
    assert status == 200
    old = body["result"]
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_correct",
                           {"memory_id": old["id"], "content": "The database is PostgreSQL.", "reason": "scale"})
    assert status == 200 and body["result"]["created"]
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_search", {"query": "which database", "n": "3"})
    assert status == 200 and body["result"][0]["status"] == "current"      # "3" was converted
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_why", {"memory_id": old["id"]})
    assert status == 200 and body["result"]["memory"]["status"] == "superseded"
    status, body, _ = _req(httpd, "GET", "/health")
    assert status == 200 and body["ok"]


def test_openapi_describes_every_tool(httpd):
    from engram.mcp_server import TOOLS
    status, doc, _ = _req(httpd, "GET", "/openapi.json")
    assert status == 200 and doc["openapi"].startswith("3.1")
    assert set(doc["paths"]) == {f"/v1/tools/{t['name']}" for t in TOOLS}
    op = doc["paths"]["/v1/tools/engram_correct"]["post"]
    assert op["operationId"] == "engram_correct"
    assert op["requestBody"]["content"]["application/json"]["schema"]["required"] == ["memory_id", "content"]
    assert "components" not in doc  # no token, no security scheme


def test_bad_requests_get_plain_errors(httpd):
    assert _req(httpd, "POST", "/v1/tools/nope", {})[0] == 404
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_search", {"query": "x", "n": "lots"})
    assert status == 400 and "'n' must be a whole number" in body["error"]
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_search", {"qeury": "x"})
    assert status == 400 and "unknown parameter 'qeury'" in body["error"]
    assert _req(httpd, "POST", "/v1/tools/engram_search", b"{not json")[0] == 400
    assert _req(httpd, "POST", "/v1/tools/engram_search", b"[1,2]")[0] == 400
    status, body, _ = _req(httpd, "POST", "/v1/tools/engram_correct", {"memory_id": "zzzz9999", "content": "x"})
    assert status == 422 and "no memory" in body["error"]
    assert _req(httpd, "DELETE", "/health")[0] == 405
    # The size is judged from Content-Length alone, so the body is never read (and the test can't race
    # a client that is still sending when the server hangs up).
    assert _req(httpd, "POST", "/v1/tools/engram_search", b"", declared_length=srv.MAX_BODY + 10)[0] == 413


def test_web_pages_and_forwarded_requests_are_refused_without_a_token(httpd):
    port = httpd.server_address[1]
    body = {"query": "secrets"}
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"Origin": "https://evil.example"})[0] == 403
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, host="evil.example")[0] == 403   # DNS rebinding
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"X-Forwarded-For": "8.8.8.8"})[0] == 403
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"Via": "1.1 proxy"})[0] == 403
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"Content-Type": "text/plain"})[0] == 415
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, {"Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert _req(httpd, "POST", "/v1/tools/engram_search", body, host=f"localhost:{port}")[0] == 200
    status, _, resp = _req(httpd, "GET", "/health")
    assert resp.getheader("Access-Control-Allow-Origin") is None                 # never any CORS


def test_a_token_is_required_and_compared_exactly(engram_home):
    httpd = _start(engram_home, token="s3cret-token")
    try:
        assert _req(httpd, "GET", "/health")[0] == 401
        assert _req(httpd, "GET", "/health", headers={"Authorization": "Bearer wrong"})[0] == 401
        assert _req(httpd, "GET", "/health", headers={"Authorization": "Basic s3cret-token"})[0] == 401
        assert _req(httpd, "GET", "/health", headers={"Authorization": "Bearer s3cret-token"})[0] == 200
        ok = {"Authorization": "Bearer s3cret-token"}
        assert _req(httpd, "POST", "/v1/tools/engram_search", {"query": "x"}, {**ok, "Origin": "https://evil.example"})[0] == 403
        doc = _req(httpd, "GET", "/openapi.json", headers=ok)[1]
        assert doc["security"] == [{"bearer": []}]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_network_listening_needs_a_token(engram_home):
    with pytest.raises(ValueError, match="needs a token"):
        srv.make_server("0.0.0.0", 0, None)
    assert srv.is_loopback("127.0.0.1") and srv.is_loopback("::1") and srv.is_loopback("localhost")
    assert not srv.is_loopback("0.0.0.0") and not srv.is_loopback("192.168.1.5")


def test_token_file_is_private_and_stable(engram_home):
    first = srv.load_or_create_token()
    assert len(first) >= 32 and srv.load_or_create_token() == first
    assert oct(srv.token_path().stat().st_mode & 0o777) == "0o600"


def test_cli_serve_creates_a_token_for_public_addresses_and_never_prints_it(engram_home, monkeypatch):
    started = {}

    class Fake:
        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            started["closed"] = True

    def fake_make(host, port, token, extra_hosts=()):
        started.update(host=host, token=token)
        return Fake()

    monkeypatch.setattr(srv, "make_server", fake_make)
    res = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0"])
    assert res.exit_code == 0 and started["token"] == srv.token_path().read_text().strip() and started["closed"]
    assert started["token"] not in res.output and "token" in res.output.lower()
    started.clear()
    res = CliRunner().invoke(app, ["serve"])
    assert started["token"] is None and "No token" in res.output
    monkeypatch.setattr(srv, "make_server", lambda *a, **k: (_ for _ in ()).throw(ValueError("needs a token")))
    assert CliRunner().invoke(app, ["serve"]).exit_code == 1
