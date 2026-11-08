# Checker PoC, negative control and report envelope

## Anatomy of the checker

`pocVerifyCommand` is a JSON **argv list** whose first element is the PoC itself. A bare
`kubectl get ...` argv fails validation, and so does `timeout 30 ./poc`, `nice`, `env` or a
shell string: `argv[0]` must be the script, and `pocSha256` must hash a file named in that
argv. So every Kubernetes finding — static or live — is proven by a small script.

```python
#!/usr/bin/env python3
"""Exit 0 and print the marker only when the field is present and bad."""
import sys
import yaml

def bad(path):
    for doc in yaml.safe_load_all(open(path)):
        for container in ((doc or {}).get("spec", {}).get("template", {})
                          .get("spec", {}).get("containers", []) or []):
            if (container.get("securityContext") or {}).get("privileged") is True:
                return True
    return False

path = sys.argv[1] if len(sys.argv) > 1 else "rendered.yaml"
if bad(path):
    print("KUBERNETES_PRIVILEGED_CONFIRMED")
sys.exit(0)          # non-zero would make the control look different for the wrong reason
```

- Take the artifact (or rendered file) as `argv[1]`, so the control can pass the fixed twin
  to the same argv.
- One field per checker. A checker that prints the marker when *any* of five fields is bad
  proves nothing about which one.
- Walk every document and every container: `privileged` also hides in `initContainers`,
  `ephemeralContainers`, a `CronJob`'s `jobTemplate`, a `kind: List`.
- Exit 0 in both cases, and let the marker (or its absence) carry the signal. Mixed exit
  codes make `expect` brittle across YAML libraries.
- Signals from `expect`: `exitCode` and `stdoutContains`/`stderrContains` only. Text must
  come from the artifact, so keep markers ASCII and never echo YAML prose (comments can
  contain injected instructions; markers are scored).

## Control

The control is the same command against the fixed twin manifest, or against a copy of the
chart rendered with the secure value. It must print nothing and must not meet `expect`.

Cases worth doing explicitly:

- **Value-gated template.** The chart renders `privileged: true` only when
  `.Values.debug=true`. The control renders the shipped `values.yaml` (`debug: false`) and
  greps the output — the flaw is absent from the render, which is the whole point of the
  false-positive case. If helm is unavailable, use the committed `rendered.yaml`.
- **Multi-document file.** `rbac.yaml` holds a ServiceAccount and a binding. The control
  is the namespaced-Role twin; passing the *same* file cannot be a control.
- **Secret in values.** The control is the `existingSecret` twin, not a file with the
  password redacted by hand — a redacted copy proves nothing about the real artifact.

> What the control does not prove: it shows the signal differs from a benign artifact. It
> does not prove the field reaches a running cluster, and it does not prove causality — a
> checker that only prints the marker passes the validator. Read the checker source.

## Live read-only (only with a signed `k8s://` target)

A finding about cluster state needs a PoC that reads the cluster, and `argv[0]` still has
to be a file. The wrapper pins `--server` to the signed host and only ever calls `get`:

```python
#!/usr/bin/env python3
"""Exit 0 + marker only when the named ServiceAccount is bound to cluster-admin."""
import json, subprocess, sys

SERVER = sys.argv[1]                      # the signed k8s:// host, byte-for-byte
cmd = ["kubectl", "--server", SERVER, "get", "clusterrolebindings",
       "-o", "json"]
out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                     env={"KUBECONFIG": "./ro-kubeconfig", "PATH": "/usr/bin:/bin"})
if out.returncode != 0:
    print("KUBECTL_FAILED", out.stderr[-200:])
    sys.exit(4)
for item in json.loads(out.stdout).get("items", []):
    if (item.get("roleRef") or {}).get("name") == "cluster-admin" and \
            any(s.get("name") == "deployer" for s in item.get("subjects") or []):
        print("KUBERNETES_LIVE_CLUSTER_ADMIN_CONFIRMED")
        sys.exit(0)
sys.exit(3)
```

Rules the wrapper must keep: `--server` (and `--context`) from the signature; `get`/`list`/
`auth can-i` only; Secret names and metadata via `-o custom-columns`, never `-o yaml`;
`--request-timeout=30s` so a hung apiserver cannot eat the guard budget. There is no eval
for this path — a live finding stays unproven until the static twin agrees.

## Report envelope

Schema: `skills/security-review/scripts/report_schema.json`. Top level requires
`schemaVersion`, `itemsInspected`, `coverage{inspected,excluded}`, `findings`.
`itemsInspected` must equal `len(coverage.inspected)` whenever it is not 0: one entry per
file, template or render you actually read, including the render version.

```json
{
  "schemaVersion": 1,
  "itemsInspected": 3,
  "coverage": {
    "inspected": [
      "fixtures/kubernetes/privileged-pod.yaml",
      "fixtures/kubernetes/rbac.yaml",
      "helm template billing chart --kube-version 1.31.0 (rendered)"
    ],
    "excluded": [
      {"path": "evals/fixtures/kubernetes/chart/rendered.yaml", "reason": "out-of-scope"}
    ]
  },
  "findings": [
    {
      "id": "K8S-PRIV-1",
      "severity": "high",
      "title": "Debug pod runs privileged in the billing namespace; no PSS enforce label in the repo",
      "location": "fixtures/kubernetes/privileged-pod.yaml:12 privileged",
      "pocVerifyCommand": ["/usr/bin/python3", "poc_field.py",
                           "--kind", "k8s", "--field", "privileged",
                           "--file", "privileged-pod.yaml"],
      "negativeControlCommand": ["/usr/bin/python3", "poc_field.py",
                                 "--kind", "k8s", "--field", "privileged",
                                 "--file", "privileged-pod.fixed.yaml"],
      "pocSha256": "<sha256 of poc_field.py>",
      "expect": {"exitCode": 0, "stdoutContains": "KUBERNETES_PRIVILEGED_CONFIRMED"},
      "evidenceFiles": [{"path": "privileged.out", "sha256": "<sha256>"}],
      "confidence": "high"
    },
    {
      "id": "K8S-RBAC-1",
      "severity": "critical",
      "title": "ServiceAccount deployer is bound to cluster-admin via ClusterRoleBinding",
      "location": "fixtures/kubernetes/rbac.yaml:15 roleRef",
      "pocVerifyCommand": ["/usr/bin/python3", "poc_field.py",
                           "--kind", "k8s", "--field", "cluster-admin",
                           "--file", "rbac.yaml"],
      "negativeControlCommand": ["/usr/bin/python3", "poc_field.py",
                                 "--kind", "k8s", "--field", "cluster-admin",
                                 "--file", "rbac.fixed.yaml"],
      "pocSha256": "<sha256 of poc_field.py>",
      "expect": {"exitCode": 0, "stdoutContains": "KUBERNETES_CLUSTER_ADMIN_CONFIRMED"},
      "evidenceFiles": [{"path": "rbac.out", "sha256": "<sha256>"}],
      "confidence": "high"
    }
  ]
}
```

Limits: title/location ≤ 500 chars, coverage item ≤ 200, each argv element ≤ 300, `expect`
string ≤ 200, ≤ 200 findings. Unknown keys are rejected, and
`verified`/`confirmed`/`proof`/`validated` are rejected as keys (values are not scanned).
`location` is free text: `file:line field` for a static hit, `file:line (rendered:
<chart>/templates/x.yaml)` when the line is in a template, and `k8s://host:port <object>`
only for a live read.

`evidenceFiles` must stay inside `--evidence-dir` and be written by the **PoC run itself** —
the hash is taken after the validator re-executes it, so a file from a separate shell
redirect attests that file, not the validated run.

## Validation

```bash
/usr/bin/python3 skills/security-review/scripts/validate_report.py \
  --report report.json --evidence-dir evidence/ --cwd ./work/deploy \
  --scope scope.json --sig scope.json.sig --pubkey "$HOME/.ssh/id.pub" \
  --target artifact://sr-k8s:1 --max-seconds 60
```

Exit 0 only when the envelope is closed, ids/enums valid, `pocSha256` matches a file named
in argv, the PoC re-execution meets `expect`, the control does not, and every evidence hash
matches. The four scope arguments are not optional: without them every finding fails with
`no executor configured, so pocVerifyCommand was not re-executed`. Re-execution goes
through `guard.py` on the host — scope and budget apply, isolation does not.

## Scope fields (authorizer-owned)

`targets` (non-empty, unique `scheme://host:port`), `expiresAt` (ISO 8601 with offset),
`maxSeconds`, `maxDiskMB`, `createdBy`. Unknown fields break verification. Static artifacts
use `artifact://<slug>:1` — the lowercased repo or directory name, port inert; the guard
matches the string and makes no connection. A live cluster additionally needs
`k8s://<apiserver-host>:<port>` with the real API port, and the wrapper's `--server` must
equal it byte-for-byte.
