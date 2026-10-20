"""A local HTTP interface to Engram, for apps that don't speak MCP.

``engram serve`` exposes the same tools as the MCP server, with the same rules
(corrections, evidence, argument checks), over plain HTTP + JSON::

    GET  /health                 {"ok": true, "version": "..."}
    GET  /openapi.json           OpenAPI 3.1 description (Open WebUI, n8n, ...)
    GET  /v1/tools               the tool names
    POST /v1/tools/<name>        body = the tool's arguments; reply {"result": ...}

Because memories are private, the defaults are strict:

* It listens on ``127.0.0.1`` only. Listening on any other address requires a
  token, and there is no switch to turn that off.
* Without a token (loopback only) a request is refused when it looks like it
  came from a web page rather than an app: it carries an ``Origin`` other than
  the server's own, a cross-site ``Sec-Fetch-Site``, or a ``Host`` that is not
  localhost (DNS rebinding); or when it carries proxy headers
  (``X-Forwarded-For``, ``Forwarded``, ``Via``, ...), since a forwarded server
  is no longer local. A server reached through a tunnel or forwarder that adds
  no headers can't be told apart, so set a token whenever anything forwards to it.
* With a token every request must send ``Authorization: Bearer <token>``,
  compared in constant time. The token file (``~/.engram/server/token``,
  mode 0600) is created on first use and its *contents* are never printed.
* ``POST`` needs ``Content-Type: application/json`` (a plain web form can't
  send that without a permission check the server never grants), and bodies
  are limited to 1 MB.
* No CORS headers are ever sent, so browsers can't call it from a page.
* Errors say what was wrong with the request; internal errors name only the
  error class, never paths or stack traces.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from engram import __version__, config

DEFAULT_PORT = 7742
MAX_BODY = 1_000_000
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")
# Headers a reverse proxy or tunnel adds: a request carrying them did not come
# from a local app, so it is refused unless a token proves who is asking.
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
                 "x-real-ip", "forwarded", "via", "cf-connecting-ip", "cf-ray", "true-client-ip",
                 "x-original-forwarded-for", "tailscale-user-login", "tailscale-user-name")


def is_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def token_path() -> Path:
    return config.ENGRAM_DIR / "server" / "token"


def load_or_create_token(path: Optional[Path] = None) -> str:
    """The server token, created (random, mode 0600) on first use."""
    path = path or token_path()
    try:
        value = path.read_text().strip()
        if value:
            return value
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value + "\n")
    return value


class Refusal(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def check_request(method: str, headers, token: Optional[str], bound_host: str, port: int,
                  extra_hosts: tuple = ()) -> None:
    """Raise :class:`Refusal` unless this request may reach the tools. *headers* is a Mapping-like (case-insensitive)."""
    get = lambda name: (headers.get(name) or "").strip()  # noqa: E731
    host = get("Host")
    origin = get("Origin")
    if origin and origin.lower() != f"http://{host}".lower():
        raise Refusal(403, "requests from web pages are not allowed")
    if get("Sec-Fetch-Site").lower() == "cross-site":
        raise Refusal(403, "requests from web pages are not allowed")
    if token:
        sent = get("Authorization")
        scheme, _, value = sent.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip().encode(), token.encode()):
            raise Refusal(401, "missing or wrong token: send 'Authorization: Bearer <token>'")
    else:
        if any(h in headers for h in PROXY_HEADERS):
            raise Refusal(403, "this server has no token, so it refuses forwarded requests; set a token")
        name = urlsplit("//" + host).hostname or ""
        if name not in LOOPBACK_NAMES and name not in extra_hosts:
            raise Refusal(403, "unexpected Host header")
    if method == "POST":
        ctype = get("Content-Type").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise Refusal(415, "send 'Content-Type: application/json'")


def openapi(tools: list[dict], with_token: bool) -> dict:
    """An OpenAPI 3.1 description with one operation per tool."""
    paths = {}
    for tool in tools:
        schema = {**tool["inputSchema"], "additionalProperties": False}
        paths[f"/v1/tools/{tool['name']}"] = {"post": {
            "operationId": tool["name"],
            "summary": tool["description"].split(". ")[0][:120],
            "description": tool["description"],
            "requestBody": {"required": bool(schema.get("required")),
                            "content": {"application/json": {"schema": schema}}},
            "responses": {
                "200": {"description": "The tool's result",
                        "content": {"application/json": {"schema": {
                            "type": "object", "properties": {"result": {}}}}}},
                "400": {"description": "Invalid arguments"},
                "401": {"description": "Missing or wrong token"},
            },
        }}
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "Engram", "version": __version__,
                 "description": "Local, private long-term memory: search, recall, save, correct and explain."},
        "servers": [{"url": "/"}],
        "paths": paths,
    }
    if with_token:
        doc["components"] = {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}
        doc["security"] = [{"bearer": []}]
    return doc


class EngramHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, engram, token: Optional[str], extra_hosts: tuple = ()) -> None:
        self.engram = engram              # an EngramMCPServer
        self.token = token
        self.extra_hosts = tuple(h.lower() for h in extra_hosts)
        self.lock = threading.Lock()      # the vector backends aren't safe to share across threads
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: EngramHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "Engram"
    sys_version = ""

    def log_message(self, fmt, *args):  # one short line per request, never the body
        print(f"engram serve: {self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}",
              file=sys.stderr)

    # -- plumbing ---------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if status >= 400:  # an unread request body must not be mistaken for the next request
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        host, port = self.server.server_address[:2]
        try:
            check_request(self.command, self.headers, self.server.token, host, port, self.server.extra_hosts)
        except Refusal as r:
            self._send(r.status, {"error": r.message})
            return False
        return True

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise Refusal(400, "bad Content-Length") from None
        if length > MAX_BODY:
            raise Refusal(413, f"body too large (limit {MAX_BODY:,} bytes)")
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            raise Refusal(400, "body is not valid JSON") from None
        if not isinstance(data, dict):
            raise Refusal(400, "body must be a JSON object of arguments")
        return data

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        if not self._guard():
            return
        from engram.mcp_server import TOOLS
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/health":
            self._send(200, {"ok": True, "version": __version__})
        elif path == "/openapi.json":
            self._send(200, openapi(TOOLS, bool(self.server.token)))
        elif path == "/v1/tools":
            self._send(200, {"tools": [t["name"] for t in TOOLS]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard():
            return
        from engram.lineage import LineageError
        from engram.mcp_server import TOOL_SCHEMAS
        from engram.validate import ArgumentError
        prefix = "/v1/tools/"
        path = self.path.split("?")[0]
        if not path.startswith(prefix) or path[len(prefix):] not in TOOL_SCHEMAS:
            self._send(404, {"error": "not found; see /v1/tools"})
            return
        try:
            args = self._body()
            with self.server.lock:
                result = self.server.engram.dispatch(path[len(prefix):], args)
            self._send(200, {"result": result})
        except Refusal as r:
            self._send(r.status, {"error": r.message})
        except ArgumentError as exc:
            self._send(400, {"error": f"invalid arguments: {exc}"})
        except (LineageError, LookupError) as exc:
            self._send(422, {"error": str(exc)})
        except Exception as exc:  # name the class only: messages can hold paths
            self._send(500, {"error": f"internal error ({type(exc).__name__})"})

    def do_PUT(self):
        self._send(405, {"error": "use GET or POST"})

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT, token: Optional[str] = None,
                engram=None, extra_hosts: tuple = ()) -> EngramHTTPServer:
    """Build the server. A non-loopback *host* without a *token* is refused."""
    if not is_loopback(host) and not token:
        raise ValueError(f"listening on {host} needs a token (this address is reachable from other machines)")
    if engram is None:
        from engram.mcp_server import EngramMCPServer
        engram = EngramMCPServer()
    return EngramHTTPServer((host, port), engram, token, extra_hosts)
