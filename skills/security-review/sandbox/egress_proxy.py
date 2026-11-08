#!/usr/bin/env python3
"""Minimal allowlist HTTP forward proxy (stdlib only) for the web sandbox profile.

The tool container sits on an --internal network with no route out; this sidecar is
dual-homed and is its only way out. The allowlist is generated from a verified
scope (gen-proxy-conf.py): exact host:port plus the IPs pinned at generation time.
Plain HTTP only -- CONNECT (HTTPS) is refused, and redirects are relayed as-is,
never followed. Every request is logged with an ALLOW, DENY or UPSTREAM_ERROR
decision.
"""

import argparse
import http.client
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOP_BY_HOP = {
    "connection", "proxy-connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
}
# The body is re-framed from what we buffered, so the upstream Content-Length must
# not be relayed next to ours (duplicate header).
NOT_RELAYED = HOP_BY_HOP | {"content-length"}
ALLOW = {}  # "host:port" -> first pinned IP


def log(decision, client, method, target, path, status):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp} decision={decision} client={client} method={method} "
          f"target={target} path={path} status={status}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # the access log above is the only log we want
        pass

    def _reply(self, decision, status, reason, target="-", path="-"):
        body = f"egress proxy: {reason}\n".encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        log(decision, self.client_address[0], self.command, target, path, status)

    def do_CONNECT(self):
        self._reply("DENY", 403, "CONNECT/HTTPS is not supported in v1", self.path)

    def _proxy(self):
        parts = urlsplit(self.path)
        if parts.scheme != "http" or not parts.hostname:
            return self._reply("DENY", 403, "request target must be an absolute http://host:port URL", self.path)
        try:
            port = parts.port or 80  # clients omit :80; a scope entry is always host:port
        except ValueError:
            return self._reply("DENY", 403, "invalid port", self.path)
        host = parts.hostname.lower().rstrip(".")
        target = f"{host}:{port}"
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        ip = ALLOW.get(target)
        if ip is None:
            return self._reply("DENY", 403, "target not in signed scope", target, path)

        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
            if length < 0:
                raise ValueError(raw_length)
        except ValueError:
            return self._reply("DENY", 400, f"invalid Content-Length: {raw_length!r}", target, path)
        body = self.rfile.read(length) if length else None
        # Drop every client Host spelling (http.client would add a second one if a
        # lowercase `host:` survived), then set the single Host of the pinned target.
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_BY_HOP and k.lower() != "host"}
        headers["Host"] = target  # the pinned IP must not leak into Host
        try:
            conn = http.client.HTTPConnection(ip, port, timeout=15)
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            # shortcut: the whole body is buffered in memory; cap it if large downloads matter.
            data = response.read()
            conn.close()
        except (OSError, http.client.HTTPException) as exc:
            return self._reply("UPSTREAM_ERROR", 502, f"upstream error: {exc}", target, path)

        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() not in NOT_RELAYED:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        log("ALLOW", self.client_address[0], self.command, target, path, response.status)


for _method in ("GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"):
    setattr(Handler, f"do_{_method}", Handler._proxy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--listen", default="0.0.0.0:8888")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = json.load(fh)
    for entry in config.get("allow", []):
        if entry.get("ips"):
            ALLOW[f"{entry['host']}:{entry['port']}"] = entry["ips"][0]
    if not ALLOW:
        print("empty allowlist: refusing to start", file=sys.stderr)
        return 1

    host, _, port = args.listen.rpartition(":")
    server = ThreadingHTTPServer((host or "0.0.0.0", int(port)), Handler)
    print(f"listening on {args.listen} allow={sorted(ALLOW)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
