# Container artifact checklist

One row per check. **Freq** = how often it shows up in real repos; **Impact** = how bad
when it holds and nothing else mitigates. Score them separately (freq → `confidence`,
impact → `severity`). **Static** = checkable from the artifact text alone: YES, PARTIAL
(needs the base image, the runtime or another file) or NO (needs the image or the host).
The last column is the trap that turns a naive hit into a false positive.

## Dockerfile

`final` = the last stage, the one that becomes the image.

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Non-root user | no `USER` in `final`; `USER root`; `USER 0` | YES | high | high | `USER` in a builder stage only; base image defaults (distroless `nonroot`, `node`, `nginx` unprivileged tag) already non-root — say "inherits from base" |
| Secret in `ENV` | `ENV TOKEN=${TOKEN}` or a literal credential | YES | high | high | a `$`-reference to a build arg is still baked in; a URL/name (`TOKEN_URL`, `FOO_ENDPOINT`) is not a credential |
| Secret in `ARG` used to build | `ARG NPM_TOKEN` + `RUN npm config set ..._authToken "$NPM_TOKEN"` | PARTIAL | high | high | same; the arg alone is not the flaw — the leak is the `RUN`/`ENV` that persists it into a layer |
| Secret in `COPY` | `COPY .npmrc`/`id_rsa`/`.env` into the image | YES | med | high | `COPY` into a builder stage that is discarded is clean; a later `COPY --from` of that path is not |
| Base pinned by digest | `FROM node:20` / `:latest` | YES | high | low | info note, not a finding; a digest plus tag is pinned |
| `ADD` usage | `ADD http://…`, `ADD x.tar.gz /` | YES | med | low | `ADD` for a local file with no archive/URL is equivalent to `COPY` — downgrade, do not drop |
| Download piped to shell | `curl … \| sh`, `wget -O- \| bash` | YES | high | med | info note unless the URL is unpinned http; vendor installer scripts are the intended use |
| Multi-stage build | toolchain/source in `final` | YES | med | low | a single-stage build for a compiled binary is not automatically a finding |
| `HEALTHCHECK` | absent | YES | high | info | hygiene, not security; never a `findings` entry on its own |
| Root-owned world-writable | `chmod 777`, `chown -R 777` | YES | low | med | a `tmpfs`/data dir legitimately needs write access |
| Package hygiene | `apt-get` without `--no-install-recommends`/`rm -rf /var/lib/apt/lists` | YES | high | info | image size, not security |
| Ports exposed | `EXPOSE 22`, `EXPOSE 2375` | YES | low | med | `EXPOSE` is documentation; the exposure comes from the run/publish step |
| Build secret mount | `RUN --mount=type=secret` present | YES | — | — | this is the fix; do not flag |
| Leaked layer residue | secret written then deleted in a later `RUN` | NO | med | high | needs `docker history`/image scan; report the instruction, mark residue out of scope |

## Runtime: docker run / compose service

Rendered with `docker compose config` when a compose file is present.

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Privileged | `privileged: true`, `--privileged` | YES | med | high | Podman **rootless**: not host root — downgrade; rootful daemon: escape |
| Capabilities | no `cap_drop: [ALL]`; `cap_add: [SYS_ADMIN, NET_ADMIN, SYS_PTRACE]` | YES | high | high | an app that genuinely needs one cap is still a finding but not a high if it is the only one |
| Docker socket | `/var/run/docker.sock` in `volumes`/`--mount` | YES | high | high | `:ro` is **not** read-only API access — keep it high |
| Sensitive host binds | `/`, `/etc`, `/var/run`, `/var/lib/docker`, `/proc`, `/sys`, `/dev`, `~/.ssh` | YES | med | high | a named volume is fine; `:z`/`:Z` on a host path only changes the SELinux label |
| Host namespaces | `network_mode: host`, `pid: host`, `ipc: host`, `userns_mode: host` | YES | med | high | `network_mode: host` in a CI runner container may be the only supported mode — note the context |
| Devices | `devices: ["/dev/sda:/dev/sda"]` | YES | low | high | needed for GPU devices, still a finding at lower severity |
| Read-only rootfs | no `read_only: true` (and no `tmpfs` for writable paths) | YES | high | med | an app that writes to its own image path is a real finding; `read_only` + no tmpfs breaks it, so check for both |
| Privilege escalation | no `security_opt: [no-new-privileges:true]` | YES | high | med | redundant with `cap_drop: ALL` + non-root only in part; setuid binaries still matter |
| MAC/ seccomp | `seccomp=unconfined`, `apparmor=unconfined`, `label=disable`, Quadlet `SecurityLabelDisable=true` | YES | med | high | custom profile path is not "disabled" — read the profile only if it is in the artifact |
| Service user | no `user:` and image runs as root | PARTIAL | high | high | depends on the image default; state the inference |
| Published ports | `"8080:80"`, `"0.0.0.0:8080:80"` | YES | high | med | loopback-only `"127.0.0.1:8080:80"` is clean; Docker's own iptables rules bypass UFW either way |
| Literal credentials | `environment: PASSWORD: hunter2` | YES | high | high | a `${VAR:?}` reference is clean; a committed `.env` the compose reads is the same flaw one file over |
| Compose secrets | `secrets:` used for a password | YES | — | — | compose secrets are bind mounts, not encrypted; file-based is better than `environment:` but not a fix on its own |
| Resource limits | no `mem_limit`/`cpus`/`pids_limit`/`ulimits` | YES | high | low | DoS hygiene; a dev-only compose file is a note, not a finding |
| Restart policy | `restart: always` on a crashing service | YES | low | info | not security |
| Default bridge / `icc` | implicit default network | PARTIAL | med | low | needs the daemon config; a compose file's `networks:` block is authoritative |
| Image pinning | `image: postgres:16.2` (tag) / `:latest` | YES | high | low | info note unless combined with a pulled-and-run flow |
| podman-compose parity | `cap_drop`, `read_only`, `secrets` present | PARTIAL | med | high | podman-compose ignores several of these; never credit the directive without checking the implementation |

## Podman / Quadlet (`.container`, `.pod`)

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Privileged | `Privileged=true` | YES | med | med | rootless user unit: cannot exceed the user — downgrade |
| Capabilities | `AddCapability=`, no `DropCapability=all` | YES | med | high | generator default is `DropCapability=all`; the key's absence is clean |
| SELinux | `SecurityLabelDisable=true`, `--security-opt label=disable` | YES | med | high | `label=nested` is not a disable |
| Publish | `PublishPort=0.0.0.0:8080:80` | YES | high | med | `PublishPort=8080:80` binds all interfaces too — check both forms |
| Volumes | `Volume=/etc:/host-etc:z` | YES | med | high | `:Z` private label on an app data dir is fine |
| Rootless mode | unit in `~/.config/containers/systemd` | YES | — | — | rootless mitigates several rows above; use it to lower severity, never to skip |

## Supply chain (needs a registry/image target)

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Digest pinning | tag-only reference for a production image | YES | high | med | `:latest` in a dev compose is a note |
| SBOM / signature | no `cosign`/`notation` attestation, no SBOM in the repo | PARTIAL | high | med | verification needs the registry; absent evidence is not proof of absence |
| Base provenance | unknown Docker Hub account, typosquatted name | PARTIAL | med | high | official/verified publisher and a maintained base (distroless, Chainguard) are clean |
| Layer CVEs | OS packages and vendored libs | NO | high | varies | needs a pulled image; absent tool = absent scan, never a finding |

## Out of scope (record, never report)

- `docker info`/`docker inspect`, `/etc/docker/daemon.json`, userns-remap, `icc=false`,
  `-H tcp://` without TLS, socket permissions and audit rules, live-restore, log driver.
- CIS Docker Benchmark host sections 1 and 2 (host configuration, daemon config).
- Runtime detection (Falco, Tetragon), kernel/runtime CVEs (runc, BuildKit) unless the
  artifact pins a vulnerable version in a `FROM`/install line — then it is an image-tag note.
- Actual image scanning (`trivy image`, `grype <image>`, `dockle <image>`) without a
  registry/image target in the signed scope.
