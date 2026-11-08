# PoC, negative control and report envelope

## PoC requirements

- `pocVerifyCommand` is a JSON **argv list**, first element the PoC itself. Wrappers
  (`timeout`, `nice`, `env`, a shell string) are rejected.
- It must re-run from a clean `--cwd`, take the built binary as an argument (so the
  fixed twin can be substituted for the control), and exit non-zero or print a
  non-matching string when the flaw is absent.
- `pocSha256` is the sha256 of a file named in that argv. Editing the PoC without
  re-hashing fails validation.
- `expect` may only use `exitCode`, `stdoutContains`, `stderrContains`, `httpStatus`
  (the last is unused here).
- Evidence files live under `--evidence-dir`, are hashed after re-execution, and must
  stay inside it.

Minimal Python PoC pattern:

```python
#!/usr/bin/env python3
"""Exit 0 + OVERFLOW_CONFIRMED only when ASan reports the overflow."""
import subprocess, sys
from pathlib import Path

INPUT = Path(__file__).with_name("input") / "overflow.txt"

def main():
    binary = sys.argv[1] if len(sys.argv) > 1 else "./vuln"
    proc = subprocess.run([binary, INPUT.read_text().strip()],
                          capture_output=True, text=True, timeout=30)
    if "ERROR: AddressSanitizer" in proc.stderr:
        print("OVERFLOW_CONFIRMED")
        return 0
    print("NO_OVERFLOW")
    return 3

sys.exit(main())
```

The control is the same argv with the fixed binary (or a benign input file). It must
not satisfy `expect`; a control that also prints the marker is rejected as proof.

> What the control does **not** prove: it shows the signal differs from a benign run.
> It does not prove the PoC reached the target, nor that the signal depends on the
> flaw — a PoC that only prints the marker passes the validator. Read the PoC source.

## Report envelope

Schema: `skills/security-review/scripts/report_schema.json`. Top level requires
`schemaVersion`, `itemsInspected`, `coverage{inspected,excluded}`, `findings`.
`notApplicableReason` is optional and only for an empty report
(`target-unreachable`, `out-of-scope`, `no-attack-surface`).

`itemsInspected` must equal `len(coverage.inspected)` whenever it is not 0: one entry per
file/function you actually read (the validator checks the equality only, so the unit is
whatever you list). `evidenceFiles` must stay inside `--evidence-dir` and be written by
the **PoC run itself** — the hash is taken after the validator re-executes the PoC, so an
`asan.out` from a separate shell redirect attests that file, not the validated run.

```json
{
  "schemaVersion": 1,
  "itemsInspected": 2,
  "coverage": {
    "inspected": ["binary-c vuln under ASan", "binary-c fixed (negative control)"],
    "excluded": []
  },
  "findings": [
    {
      "id": "BIN-OVERFLOW-1",
      "severity": "high",
      "title": "Stack buffer overflow in copy_name (strcpy into char[64])",
      "location": "fixtures/binary-c/vuln.c copy_name",
      "pocVerifyCommand": ["/usr/bin/python3", "poc_overflow.py", "./vuln"],
      "negativeControlCommand": ["/usr/bin/python3", "poc_overflow.py", "./fixed"],
      "pocSha256": "<sha256 of poc_overflow.py>",
      "expect": {"exitCode": 0, "stdoutContains": "OVERFLOW_CONFIRMED"},
      "evidenceFiles": [{"path": "asan.out", "sha256": "<sha256 of evidence/asan.out>"}],
      "confidence": "high"
    }
  ]
}
```

Limits: title/location ≤ 500 chars, coverage item ≤ 200, each argv element ≤ 300,
`expect` string ≤ 200, ≤ 200 findings. Unknown keys are rejected, and
`verified`/`confirmed`/`proof`/`validated` are rejected as keys (values are not scanned).

## Validation

```bash
/usr/bin/python3 skills/security-review/scripts/validate_report.py \
  --report report.json --evidence-dir evidence/ --cwd ./work \
  --scope scope.json --sig scope.json.sig --pubkey "$HOME/.ssh/id.pub" \
  --target exec://vuln:1 --max-seconds 60
```

Exit 0 only when: the envelope is closed, ids/enums valid, `pocSha256` matches a file
named in argv, the PoC re-execution meets `expect`, the control does not, and every
evidence hash matches. The four scope arguments are not optional: without them there is
no executor and every finding fails with `no executor configured, so pocVerifyCommand
was not re-executed`. With them, re-execution goes through `guard.py` on the host, so
scope and budget apply but the process is not isolated.

## Scope fields (authorizer-owned)

The manifest the human signs has exactly:
`targets` (non-empty, unique `scheme://host:port`), `expiresAt` (ISO 8601 with offset),
`maxSeconds`, `maxDiskMB`, `createdBy`. Unknown fields break verification. For local
binaries the identity entry is `exec://<basename>:1` — the guard matches it exactly;
no connection is made to that name/port.
