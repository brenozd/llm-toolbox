#!/usr/bin/env python3
"""PoC for the seeded stack buffer overflow: run a binary with the long input.

Exit 0 + "OVERFLOW_CONFIRMED" only when ASan reports the overflow.
Usage: poc_overflow.py ./vuln   (negative control: poc_overflow.py ./fixed)
"""

import subprocess
import sys
from pathlib import Path

INPUT = Path(__file__).with_name("input") / "overflow.txt"


def main():
    binary = sys.argv[1] if len(sys.argv) > 1 else "./vuln"
    payload = INPUT.read_text().strip()
    try:
        proc = subprocess.run([binary, payload], capture_output=True, text=True, timeout=30)
    except OSError as exc:
        print(f"cannot run {binary}: {exc}")
        return 2
    if "AddressSanitizer" in proc.stderr or "stack-buffer-overflow" in proc.stderr:
        print("OVERFLOW_CONFIRMED")
        first = next((line for line in proc.stderr.splitlines() if "ERROR" in line), "")
        print(first)
        return 0
    print("NO_OVERFLOW")
    return 3


if __name__ == "__main__":
    sys.exit(main())
