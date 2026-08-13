"""tests/test_browser_readiness.py — V16 Track W14-1 Item 10

Uses a real local HTTP server (stdlib http.server) rather than mocking
urllib internals, so this exercises the actual polling loop against a
real socket the same way it behaves against uvicorn.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from main import _wait_for_health

pytestmark = pytest.mark.unit


class _OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):  # silence test output
        pass


class _DelayedOKHandler(BaseHTTPRequestHandler):
    """Answers 404 for the first `delay_requests` requests, then 200 —
    simulates the API server being up but not yet fully ready."""
    delay_requests = 3
    _count = 0

    def do_GET(self):
        type(self)._count += 1
        if type(self)._count <= type(self).delay_requests:
            self.send_response(503)
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def _serve(handler_cls, port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestWaitForHealth:
    def test_returns_true_immediately_when_server_already_up(self):
        port = _free_port()
        server = _serve(_OKHandler, port)
        try:
            start = time.monotonic()
            assert _wait_for_health(port, timeout=5.0, poll_interval=0.05) is True
            assert time.monotonic() - start < 2.0
        finally:
            server.shutdown()

    def test_returns_false_on_timeout_when_nothing_listening(self):
        port = _free_port()  # nothing bound to this port
        start = time.monotonic()
        result = _wait_for_health(port, timeout=1.0, poll_interval=0.1)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed >= 1.0
        assert elapsed < 3.0  # doesn't hang well past the timeout

    def test_becomes_true_once_server_starts_answering(self):
        # Simulates the real race this item fixes: server not ready
        # immediately, becomes ready shortly after.
        port = _free_port()
        _DelayedOKHandler._count = 0
        server = _serve(_DelayedOKHandler, port)
        try:
            assert _wait_for_health(port, timeout=5.0, poll_interval=0.05) is True
        finally:
            server.shutdown()

    def test_never_raises_even_against_a_closed_port(self):
        # Regression guard: a health check that can itself crash
        # startup would be worse than the fixed sleep it replaces.
        port = _free_port()
        try:
            _wait_for_health(port, timeout=0.3, poll_interval=0.1)
        except Exception as exc:
            pytest.fail(f"_wait_for_health raised: {exc!r}")
