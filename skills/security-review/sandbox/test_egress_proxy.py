"""Unit tests for egress_proxy.py -- no container, no runtime, no network.

The proxy handler and a fake upstream both run in this process on 127.0.0.1.
"""

import importlib.util
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROXY_PY = Path(__file__).resolve().parent / "egress_proxy.py"
BODY = b"upstream-body\n"
SEEN_HOSTS = []  # every Host the upstream received, one list per request


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        SEEN_HOSTS.append(self.headers.get_all("Host") or [])
        self.send_response(200)
        self.send_header("X-Upstream", "yes")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def upstream():
    SEEN_HOSTS.clear()
    srv = _serve(_Upstream)
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def proxy(monkeypatch):
    """(module, port, decisions) with the module's log() replaced by a recorder."""
    spec = importlib.util.spec_from_file_location("egress_proxy", PROXY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    decisions = []
    monkeypatch.setattr(mod, "log", lambda decision, *rest: decisions.append(decision))
    mod.ALLOW.clear()
    srv = _serve(mod.Handler)
    yield mod, srv.server_address[1], decisions
    srv.shutdown()
    srv.server_close()
    mod.ALLOW.clear()


def raw(port, request):
    """Send a raw request and read the whole response (Connection: close)."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def parse(response):
    head, _, body = response.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    names = []
    for line in lines[1:]:
        names.append(line.partition(":")[0].strip().lower())
    return status, names, body


def get(port, target):
    return raw(port, f"GET {target} HTTP/1.1\r\nHost: {target.split('/')[2]}\r\n"
                     f"Connection: close\r\n\r\n".encode())


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_invalid_content_length_is_400_deny(proxy):
    mod, port, decisions = proxy
    mod.ALLOW[f"127.0.0.1:{port}"] = "127.0.0.1"
    response = raw(port, f"POST http://127.0.0.1:{port}/ HTTP/1.1\r\n"
                         f"Host: 127.0.0.1:{port}\r\nContent-Length: not-a-number\r\n"
                         f"Connection: close\r\n\r\n".encode())
    status, _, body = parse(response)
    assert status == 400, (status, body)
    assert decisions == ["DENY"]


def test_upstream_failure_logged_as_upstream_error(proxy):
    mod, port, decisions = proxy
    dead = free_port()
    mod.ALLOW[f"127.0.0.1:{dead}"] = "127.0.0.1"
    status, _, _ = parse(get(port, f"http://127.0.0.1:{dead}/"))
    assert status == 502
    assert decisions == ["UPSTREAM_ERROR"]


@pytest.mark.parametrize("spelling", ["host", "HOST", "Host"])
def test_client_host_is_replaced_case_insensitively(proxy, upstream, spelling):
    """One Host upstream, equal to the pinned target, whatever case the client used."""
    mod, port, decisions = proxy
    mod.ALLOW[f"127.0.0.1:{upstream}"] = "127.0.0.1"
    request = (f"GET http://127.0.0.1:{upstream}/ HTTP/1.1\r\n{spelling}: evil.example\r\n"
               f"Connection: close\r\n\r\n").encode()
    status, _, body = parse(raw(port, request))
    assert status == 200, body
    assert SEEN_HOSTS == [[f"127.0.0.1:{upstream}"]], SEEN_HOSTS
    assert decisions == ["ALLOW"]


def test_content_length_relayed_once(proxy, upstream):
    mod, port, decisions = proxy
    mod.ALLOW[f"127.0.0.1:{upstream}"] = "127.0.0.1"
    status, names, body = parse(get(port, f"http://127.0.0.1:{upstream}/"))
    assert status == 200
    assert body == BODY
    assert names.count("content-length") == 1, names
    assert "x-upstream" in names
    assert decisions == ["ALLOW"]
