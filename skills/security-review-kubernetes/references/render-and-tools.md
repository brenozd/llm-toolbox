# Render recipes, banned flags and the scanner matrix

Everything here is offline. `export KUBECONFIG=/dev/null` first: with no kubeconfig, a
command that needs a cluster fails loudly instead of reaching one.

## Rendering

### Helm

```bash
export KUBECONFIG=/dev/null
helm template billing ./chart --namespace billing \
  --kube-version 1.31.0 \
  --values ./values.yaml --values ./values-prod.yaml \
  --api-versions networking.k8s.io/v1,cert-manager.io/v1 \
  --include-crds > rendered.yaml
helm template billing ./chart --debug --show-only templates/deployment.yaml   # one template
```

- **`--kube-version` is required** and is recorded in the report. It sets
  `Capabilities.KubeVersion`, which charts branch on; it is not a schema check.
- `--api-versions` is how a chart learns that a CRD exists. Without it, a chart that
  guards `cert-manager.io/v1` renders the fallback path. Take the list from the CRDs in
  the repo, not from a cluster.
- Render each shipped `values` file separately: the hardened staging file is not the prod
  one, and a clean render of the wrong file is a false negative.
- `--include-crds` when the CRDs live in `crds/`; they are skipped by default.
- The output carries `# Source: <chart>/templates/<file>.yaml` comments — use them to map
  a rendered object back to its template, then to the template's line.

### Kustomize

```bash
kubectl kustomize ./overlay/prod > rendered-kustomize.yaml   # built into kubectl (5.0.4 here)
```

`kubectl kustomize` takes the directory holding a `kustomization.yaml` (or `-` for stdin),
resolves local bases and overlays, and never contacts a cluster. Without that file it
errors (`unable to find one of 'kustomization.yaml', 'kustomization.yml' or
'Kustomization'`), so a flat folder of manifests is read directly instead of rendered. A remote base (`github.com/...`, `https://...`,
`git@...`) is a clone over the network: out of scope — record it and review the vendored
copy if there is one.

### No rendering needed

Plain `*.yaml` manifests are read as they are. Multi-document files: split on `---` and
check every document (a `kind: List` wraps several objects).

## Banned flags (each one is network or host execution)

| Flag | Why |
|---|---|
| `helm --post-renderer`, `--post-renderer-args` | runs an arbitrary local binary as you |
| `helm dependency build`/`update`, `--dependency-update` | fetches charts from a remote repo |
| `helm --repo`, `--version` with a repo, any `helm repo add` | network, and the chart you review is not the vendored one |
| `helm --enable-dns` | template functions resolve DNS (network egress from a render) |
| `helm --dry-run=server`, `--kube-apiserver`, `--kubeconfig` | a live call |
| `helm install`/`upgrade`/`uninstall`, `helm test` | writes |
| `kubectl apply/create/delete/patch/replace/exec/cp/port-forward/proxy` | writes or tunnels |
| `kubectl --dry-run=server` | admission against the real apiserver |
| remote kustomize bases | clone over the network |
| `kubectl create --dry-run=client` | not offline: it still resolves API discovery, and fails with `Get "http://localhost:8080/api?timeout=32s": connection refused` (verified on v1.29) |

## Scanner matrix

| Tool | Command (offline) | Catches | Misses / caveat |
|---|---|---|---|
| kubeconform | `kubeconform -strict -summary -kubernetes-version 1.31.0 -ignore-missing-schemas rendered.yaml` | schema and API-version validity, typos in field names | no security rules at all; CRDs need `-schema-location` with the repo's schemas |
| kubescape | `kubescape scan rendered.yaml --format json --output ks.json` (offline: `kubescape download artifacts --output dir`, then `--use-artifacts-from dir`) | PSS/NSA/CIS-mapped controls, RBAC | best measured accuracy is still 43.8% static in the ISSTA 2026 benchmark — triage every hit |
| kube-linter | `kube-linter lint rendered.yaml --format json` | a small default policy set, fast | few policies; EMSE 2025 calls it the narrowest set — never the only tool |
| kubesec | `kubesec scan rendered.yaml` | privileged, host namespaces, caps, seccomp, docker.sock, limits | score, not a report; no RBAC/NetworkPolicy |
| polaris | `polaris audit --audit-path ./rendered-dir --format json` | workload hygiene, limits, probes | config-hygiene oriented |
| trivy config | `trivy config --skip-db-update ./dir` | misconfig bundle, Secrets in YAML | no RBAC graph, noisy severity |
| checkov / kics | `checkov -d ./dir -o json`; `kics scan -p ./dir -o out.json` | broad IaC coverage | documented FPs (e.g. Checkov CKV_K8S_95), OSS severities are coarse |
| kyverno CLI | `kyverno apply policy.yaml --resource rendered.yaml -o json` | your own PSS/Kyverno policy, offline | needs the policy written first |
| conftest | `conftest test --output json rendered.yaml -p policy/` | Rego policy | same |
| kube-bench | `kube-bench --json` | CIS on a **live node** | not a manifest scanner; out of scope |
| kubeaudit | — | archived 2024-10, recommends kube-bench | do not add |
| kube-score | `kube-score score rendered.yaml -o json` | overlaps kube-linter, slower | optional, skip by default |

Order on this host: **kubeconform → kubescape → kube-linter → manual**. The manual pass is
mandatory regardless; the tools only add coverage and cross-check the rows you already have.

### Degradation

1. No scanners at all (this host): render, then `references/checklist.md` row by row. Say
   in the message outside the envelope that no scanner ran — the schema has no
   "tool-missing" value, so a missing scan is simply absent from `coverage.inspected`.
2. kubeconform present but kubescape absent: schema validity plus the manual pass; a
   schema error is a finding only if it means the object is rejected by the apiserver.
3. `helm` absent and the chart is vendored: review the committed `rendered.yaml` if the
   repo keeps one, and say it was not re-rendered for the pinned version. If there is no
   rendered copy, the chart's value-gated branches are unreadable — record the chart under
   `coverage.excluded` with `out-of-scope`.
4. `kubectl` absent: no kustomize render; review the base manifests and note that patches
   were not applied.

### Interpreting hits

- Two tools agreeing on the same object and field is one finding, `confidence` up. Do not
  double-count by severity.
- A scanner hit on a template that renders a safe value is a false positive — the render,
  not the template, is the evidence.
- Scanner severity is calibrated for clusters that enforce nothing. Lower it when an
  admission policy or namespace label blocks the config, and say which one.
- `:latest`, missing probes, missing `HEALTHCHECK`, and `curl | sh` are info notes; never
  a `findings` entry on their own.
