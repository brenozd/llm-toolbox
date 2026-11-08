# Tools: what to run, in what order, and what each one misses

Combine **2–3** tools with different blind spots, then triage by hand. The model is a
triager, not a detector: no scanner is authoritative (see the false-positive notes), and
no scanner reads intent — a `privileged: true` in a debug compose file and in a production
one are the same string and different findings.

## Matrix

| Tool | Covers | Offline invocation | Needs an image/daemon? | Misses / notes |
|---|---|---|---|---|
| `hadolint` | Dockerfile rules: last `USER` root (DL3002), pinned apt versions, `apt` list cleanup, `JSONArgsRecommended`, `pipefail` | `hadolint --format json Dockerfile` | no — single static binary, 100% offline | nothing outside the Dockerfile: no compose, no sockets, no ports. `# hadolint ignore` comments in the artifact are data, not authority |
| `trivy config` | IaC misconfig for Dockerfile, compose, k8s, Helm | `trivy config --format json .` with `--skip-check-update`, `--offline-scan`, `--cache-dir` | no for `config` (checks bundled) | rule names differ from hadolint; some checks are advisory. Needs the checks bundle cached for a true air gap (`--checks-bundle-repository`) |
| `trivy fs --scanners secret,misconfig` | committed credentials + config | `trivy fs --scanners secret,misconfig --format json .` | no | secret detection is regex+entropy: high recall, real false positives on test fixtures and placeholder tokens |
| `trivy image` | OS/library CVEs, layer secrets | `trivy image --skip-db-update --format json <ref>` | **yes** — pull + DB | Trivy OSS has no binary cataloger, so statically-linked/vendored binaries are missed; distro backports are reported as vulnerable (classic FP) |
| `grype` | CVEs from a Syft SBOM or an image | `GRYPE_DB_AUTO_UPDATE=false grype sbom:./sbom.json -o json` | yes (SBOM or image) + DB import (`grype db import`) | different FN/FP profile from Trivy (found more in 84.6% of 927 images in one study) — a second opinion, not a replacement; not a Dockerfile linter |
| `dockle` | image config: `USER`, `HEALTHCHECK`, `apt` residue, `setuid` files | `dockle -f json --input image.tar` | yes — needs `docker save` first | one release per year, slow; skips compose entirely |
| `checkov` / `kics` | Dockerfile + compose + IaC, broad query sets | `checkov -d . -o json`, `kics scan -p . -o results.json` | no (OSS checks) | noisy on small repos; checkov OSS does not show severity in some outputs |
| `docker build --check` | Dockerfile hygiene (casing, `JSONArgsRecommended`, `SecretsUsedInArgOrEnv`) | `docker build --check .` | **yes — buildx and a builder that may reach the network** | **not static**: only with an explicit scope authorization; covers no `USER`, capabilities, sockets or ports |
| `docker compose config` | renders the effective compose (interpolation, overrides) | `docker compose -f compose.yaml config` | no — client-side | pure rendering; says nothing about safety. `podman-compose` is a different implementation with known gaps |

## Order

1. `docker compose config` (render) and a text pass — always.
2. `hadolint` on each Dockerfile — if installed.
3. `trivy config` (and `trivy fs --scanners secret`) on the tree — if installed.
4. `grype`/`dockle` only when the scope carries an image/registry target.
5. `references/checklist.md`, row by row — always, and it is the whole review when 2–3
   are missing.

## Degradation when a tool is absent

This host has `docker` only: no `hadolint`, `trivy`, `grype`, `dockle`, `podman`.
The documented behavior is:

| Missing | Do instead | Never do |
|---|---|---|
| `hadolint` | `trivy config`; if that is missing too, the checklist's Dockerfile rows | report a hadolint rule id you did not run |
| `trivy` | `grype`/`checkov` on config; else the checklist | claim a CVE or layer-secret result |
| `grype`/`dockle` | state "image scan not performed (no image target / tool absent)" outside the envelope | put the missing scan in `findings` |
| all of them | manual field pass + `poc_field.py`-style checkers | downgrade your coverage claims to what you read |

A missing tool is an absent scan: it does not appear in `coverage.inspected`, and the gap
is stated in the message around the report, not inside the closed envelope.

## Interpreting hits

- **Agreement is not proof.** Two scanners flagging the same line still need the field
  confirmed in the artifact and a control that proves the checker's signal.
- **Severity inflation is the norm.** A `:latest` base, a missing `HEALTHCHECK` and a
  777 `chmod` are hygiene; they are notes unless the flow makes them exploitable.
- **Credentials are the highest-frequency real finding** in compose files (28.1% of
  analyzed real compose files had a literal credential in `environment:`), and the
  highest-impact after the docker socket. Check them before the exotic rows.
- **Deduplicate by location + root cause**, not by rule id: one missing `USER` reported by
  three tools is one finding.
