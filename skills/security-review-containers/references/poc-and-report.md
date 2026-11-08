# Checker PoC, negative control and report envelope

A container artifact has no process to attack, so the PoC is a **checker**: it reads the
artifact, prints a marker only when the named field is present *and* bad, and exits 0
either way. The control is the same checker against the fixed artifact — it must print
nothing and must not meet `expect`.

## Anatomy of the checker

```python
#!/usr/bin/env python3
"""CONTAINER_ROOT_USER_CONFIRMED only when the final stage declares no non-root USER."""
import re, sys
from pathlib import Path

def final_stage(text):
    stages, cur = [], []
    for line in text.splitlines():
        if re.match(r"\s*FROM\s", line, re.I):
            if cur: stages.append(cur)
            cur = [line]
        else: cur.append(line)
    stages.append(cur)
    return [l for l in stages[-1] if not l.strip().startswith("#")]

def main():
    path = Path(sys.argv[1])                       # argv[1] = artifact, so the twin swaps in
    users = [l for l in final_stage(path.read_text()) if re.match(r"\s*USER\s+", l, re.I)]
    bad = not users or re.search(r"USER\s+(root|0)\s*$", users[-1], re.I)
    if bad:
        print("CONTAINER_ROOT_USER_CONFIRMED")
    return 0

sys.exit(main())
```

Rules that come from the validator, not from taste:

- `argv[0]` is the checker itself — `timeout`, `nice`, `env`, `sh -c` are rejected.
- `pocSha256` is the sha256 of a file named in that argv; edit → re-hash → rerun.
- `expect` may use only `exitCode`, `stdoutContains`, `stderrContains`, `httpStatus`.
- The artifact goes in as an argument, never hard-coded, so the control is the same argv
  with `Dockerfile.fixed` / `compose.fixed.yaml`.
- If the checker writes an evidence file, it must write it **itself**, under
  `--evidence-dir`; the hash is taken after the validator re-executes the PoC, so a file
  from a separate shell redirect attests that shell, not the validated run.

The working example is `skills/security-review/evals/fixtures/poc_field.py`: one stdlib
checker, `--kind {dockerfile,compose} --field {root-user,secret-env,docker-sock,env-secret}
--file PATH`, Dockerfile parsing stdlib-only and compose parsing with PyYAML. Reuse its
shape; do not copy the fixture's field list into a client repo.

## What the control does and does not prove

It proves the marker depends on the artifact content (fixed twin → no marker). It does not
prove exploitability: `privileged: true` present is not an escape performed, and a checker
that only prints the marker passes the validator regardless. Severity comes from triage
(`references/checklist.md`), not from the checker.

## Report envelope

Schema: `skills/security-review/scripts/report_schema.json`. Top level requires
`schemaVersion`, `itemsInspected`, `coverage{inspected,excluded}`, `findings`;
`notApplicableReason` (`target-unreachable`, `out-of-scope`, `no-attack-surface`) is only
for an empty report. `itemsInspected` must equal `len(coverage.inspected)`.

```json
{
  "schemaVersion": 1,
  "itemsInspected": 3,
  "coverage": {
    "inspected": ["containers Dockerfile (all stages)", "containers compose.yaml (rendered)",
                  "containers Dockerfile.fixed + compose.fixed.yaml (controls)"],
    "excluded": ["image layer scan: no registry target in scope"]
  },
  "findings": [
    {
      "id": "CON-ROOT-1",
      "severity": "high",
      "title": "Final stage declares no USER, so the container runs as uid 0",
      "location": "fixtures/containers/Dockerfile final stage",
      "pocVerifyCommand": ["/usr/bin/python3", "$SR/evals/fixtures/poc_field.py",
                           "--kind", "dockerfile", "--field", "root-user", "--file", "Dockerfile"],
      "negativeControlCommand": ["/usr/bin/python3", "$SR/evals/fixtures/poc_field.py",
                                 "--kind", "dockerfile", "--field", "root-user",
                                 "--file", "Dockerfile.fixed"],
      "pocSha256": "<sha256 of evals/fixtures/poc_field.py>",
      "expect": {"exitCode": 0, "stdoutContains": "CONTAINERS_ROOT_USER_CONFIRMED"},
      "evidenceFiles": [],
      "confidence": "high"
    },
    {
      "id": "CON-DOCKER-SOCK-1",
      "severity": "high",
      "title": "App container mounts /var/run/docker.sock, which is root on the host",
      "location": "fixtures/containers/compose.yaml service app volumes",
      "pocVerifyCommand": ["/usr/bin/python3", "$SR/evals/fixtures/poc_field.py",
                           "--kind", "compose", "--field", "docker-sock", "--file", "compose.yaml"],
      "negativeControlCommand": ["/usr/bin/python3", "$SR/evals/fixtures/poc_field.py",
                                 "--kind", "compose", "--field", "docker-sock",
                                 "--file", "compose.fixed.yaml"],
      "pocSha256": "<sha256 of evals/fixtures/poc_field.py>",
      "expect": {"exitCode": 0, "stdoutContains": "CONTAINERS_DOCKER_SOCK_CONFIRMED"},
      "evidenceFiles": [],
      "confidence": "high"
    }
  ]
}
```

Limits: `title`/`location` ≤ 500 chars, coverage item ≤ 200, each argv element ≤ 300,
`expect` string ≤ 200, ≤ 200 findings. Unknown keys are rejected, and
`verified`/`confirmed`/`proof`/`validated` are rejected as keys (values are not scanned).
`$SR` is `skills/security-review` from the repo root; the checker path must be absolute
because re-execution runs with `--cwd ./work`, so a path relative to the report does not
resolve.

Severity/confidence vocabulary — **frequency is not severity**: a literal credential in
`environment:` is `confidence: high` (constant in real repos) and `severity: high`
(single-point compromise of the backing service); a tag-only `FROM` is `confidence: high`
with `severity: low`.

## Validation

```bash
/usr/bin/python3 skills/security-review/scripts/validate_report.py \
  --report report.json --evidence-dir evidence/ --cwd ./work \
  --scope scope.json --sig scope.json.sig --pubkey "$HOME/.ssh/id.pub" \
  --target artifact://my-app:1 --max-seconds 60
```

Exit 0 only when: the envelope is closed, ids/enums valid, `pocSha256` matches a file
named in argv, the PoC re-execution meets `expect`, the control does not, and every
evidence hash matches. The four scope arguments are not optional — without them no
executor is configured and every finding fails re-execution. With them, re-execution goes
through `guard.py` **on the host**: scope and budget apply, the process is not isolated.

## Scope fields (authorizer-owned)

`targets` (non-empty, unique `scheme://host:port`), `expiresAt` (ISO 8601 with offset),
`maxSeconds`, `maxDiskMB`, `createdBy`; unknown fields break verification. For a static
artifact the identity entry is `artifact://<slug>:1` — lowercased repo or directory name,
the port is an inert placeholder guard matches byte-for-byte, and **it binds no path**:
`--cwd` still decides what the checker can read. That is the documented limit, not a
safety property.
