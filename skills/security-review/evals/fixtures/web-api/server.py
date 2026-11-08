#!/usr/bin/env python3
"""Eval fixture: a tiny HTTP API with exactly one seeded flaw.

SEEDED (do not "fix"): GET /search?q= builds SQL by string concatenation, so a
UNION payload returns the row whose name is LEAKED_SECRET_9f3.

Controls that look exploitable but are NOT:
  GET /search-safe?q=  same LIKE search, parameterized with a bound '?'.
  GET /echo?msg=       reflects the input through html.escape().

Offline: binds 127.0.0.1 only. stdlib only (http.server + sqlite3 in memory).
"""

import argparse
import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SECRET = "LEAKED_SECRET_9f3"
DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
DB.executemany("INSERT INTO users VALUES(?, ?)", [(1, "alice"), (2, "bob")])
DB.commit()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, ctype, body):
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/search":
            # SEEDED FLAW: user input concatenated into SQL.
            sql = "SELECT id, name FROM users WHERE name LIKE '%" + query.get("q", [""])[0] + "%'"
            try:
                rows = DB.execute(sql).fetchall()
            except sqlite3.Error as exc:
                self._send(400, "text/plain", f"error: {exc}")
                return
            self._send(200, "application/json", json.dumps({"rows": rows}))
        elif url.path == "/search-safe":
            # Control: same query, correctly parameterized.
            rows = DB.execute(
                "SELECT id, name FROM users WHERE name LIKE ?",
                (f"%{query.get('q', [''])[0]}%",),
            ).fetchall()
            self._send(200, "application/json", json.dumps({"rows": rows}))
        elif url.path == "/echo":
            # Control: reflected, but escaped.
            self._send(200, "text/html", "<p>" + html.escape(query.get("msg", [""])[0]) + "</p>")
        elif url.path == "/":
            self._send(200, "text/plain", "web-api fixture\n")
        else:
            self._send(404, "text/plain", "not found")

    def log_message(self, *args):  # keep the test output quiet
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
