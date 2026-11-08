#!/usr/bin/env python3
"""Turn a verified scope into the egress proxy allowlist.

Input is the dict returned by guard.verify_scope() -- JSON on stdin (--scope -) or a
file. Output is the proxy config: every http:// target with the IPs resolved right
here, once. The proxy never resolves a name at request time, so DNS cannot move a
request to a host the scope did not authorize.

v1 is plain HTTP only: https:// targets are skipped (fail closed) and reported on
stderr. Nothing is guessed -- an unresolvable host aborts generation.
"""

import argparse
import json
import socket
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", required=True, help="verified scope JSON, or - for stdin")
    parser.add_argument("--out", required=True, help="proxy config to write")
    parser.add_argument("--listen", default="0.0.0.0:8888")
    args = parser.parse_args()

    try:
        scope = json.load(sys.stdin) if args.scope == "-" else json.load(open(args.scope))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read scope: {exc}", file=sys.stderr)
        return 1
    if not isinstance(scope, dict) or not isinstance(scope.get("targets"), list):
        print("scope has no targets list", file=sys.stderr)
        return 1

    allow, skipped, seen = [], [], set()
    for target in scope["targets"]:
        scheme, _, rest = target.partition("://")
        host, _, port_text = rest.rpartition(":")
        if not scheme or not host or not port_text.isdigit():
            print(f"invalid target: {target!r}", file=sys.stderr)
            return 1
        if scheme != "http":
            skipped.append(target)
            continue
        port = int(port_text)
        key = (host.lower().rstrip("."), port)
        if key in seen:
            print(f"duplicate endpoint: {target}", file=sys.stderr)
            return 1
        seen.add(key)
        try:
            infos = socket.getaddrinfo(key[0], port, type=socket.SOCK_STREAM)
        except OSError as exc:
            print(f"cannot resolve {key[0]}:{port}: {exc}", file=sys.stderr)
            return 1
        # Sorted for a stable file; the proxy uses the first address.
        ips = sorted({info[4][0] for info in infos})
        allow.append({"scheme": "http", "host": key[0], "port": port, "ips": ips})

    if not allow:
        print("no http:// targets in scope (v1 proxy is HTTP only)", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"listen": args.listen, "allow": allow}, fh, indent=2)
        fh.write("\n")
    for target in skipped:
        print(f"skipped (not http, unsupported in v1): {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
