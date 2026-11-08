# security-review sandbox

Containment for the tools the skill runs. One shared image, two profiles:

| profile | script | network | tools |
|---|---|---|---|
| web recon | `run-web.sh` | `--internal` + dual-homed egress proxy | curl, nuclei, sqlmap |
| binary-c | `run-c.sh` | `--network none` | afl++, clang/gcc + ASan, gdb, frida |

Both run with `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only`,
`--pids-limit 256`; the C profile also limits CPUs, shm and the `/work` tmpfs.

## Build

```sh
docker build -t security-review-sandbox:local skills/security-review/sandbox
# or: CONTAINER_RUNTIME=podman SANDBOX_IMAGE=security-review-sandbox:local ...
```

The build needs network access once (Debian packages, nuclei release, templates,
frida wheels). Runtime does not.

## Web profile

```sh
skills/security-review/sandbox/run-web.sh scope.json scope.json.sig ~/.ssh/id.pub \
    -- nuclei -duc -t /opt/nuclei-templates -u http://target.example:8080
```

1. `guard.verify_scope()` checks the signature and expiry; nothing runs if it fails.
2. `gen-proxy-conf.py` turns that dict into the proxy allowlist: only `http://`
   targets, each with the IPs resolved **at generation time**.
3. The tool container joins `security-review-internal-$$` (`--internal`: no route out;
   per-run name so concurrent runs do not tear each other's network down).
   A sidecar `egress_proxy.py` is dual-homed and is the only egress. It refuses
   `CONNECT` (HTTPS), relays redirects without following them, and logs every
   request as `decision=ALLOW|DENY ... status=...` (`docker logs <proxy>`).

`HTTP_PROXY` points at the sidecar; `HTTPS_PROXY` is set empty on purpose.

The host `WORKDIR` is mounted **read-only** at `/work`; the reviewed repo cannot be
modified by a compromised tool. Tool output goes to `$SANDBOX_OUT` (`/work-out`),
which is a host directory mounted read-write, so it survives `--rm`:

```sh
OUT_DIR=./recon-out skills/security-review/sandbox/run-web.sh scope.json scope.json.sig \
    ~/.ssh/id.pub -- nuclei -duc -t /opt/nuclei-templates -o /work-out/nuclei.txt \
    -u http://target.example:8080
ls recon-out/nuclei.txt          # written by the tool, still there after the run
```

`OUT_DIR` defaults to a fresh `mktemp -d` (mode 0700, kept as-is: the container runs as
the caller's uid, so it writes there); its path is printed on stderr before the run, so
output is never lost even when you forget to set it. A caller-supplied `OUT_DIR` is used
as-is: `run-web.sh` never changes its permissions, and only warns on stderr if it is not
writable. Writes to `/work` fail (read-only file system).

**Who owns the output.** The tool container runs with `--user $(id -u):$(id -g)`, so
files under `OUT_DIR` belong to the user who invoked `run-web.sh` (mode `0644`/`0640`
by umask, no root-owned leftovers, no `sudo rm` needed). `--user` also drops
supplementary groups, so `run-web.sh` passes `--group-add` for each of the caller's
other groups: an `OUT_DIR` shared through a secondary group (`chgrp`, mode `0770`) stays
writable. `HOME` is `/tmp` inside the container, a `mode=1777` tmpfs, so config writes
stay writable for that uid.

**`nosuid`.** `/work-out` is a plain host bind mount, not `nosuid`, so a
setuid/setgid bit on a file written there is honoured by the *host* filesystem. With
`--user` the writer is your uid, so the bit can only mean "setuid to me" (verified:
`chmod 4755` inside the container survives on the host as `-rwsr-xr-x brenozd`); if any
container writing that directory does run as root, the same bit becomes a live
setuid-root binary. Nothing in `OUT_DIR` is trustworthy either way: do not execute it,
and prefer an `OUT_DIR` on a filesystem mounted `nosuid` (or check with
`find "$OUT_DIR" -perm /6000`) before anyone runs anything from it.

## Binary-c profile

```sh
skills/security-review/sandbox/run-c.sh ./work -- bash
# inside: clang -fsanitize=address ...; afl-fuzz ...; gdb ...; frida -f ./target
```

`/work` is a size-limited tmpfs (512 MB) with `exec`; the host `./work` is mounted
at `/out` so results survive. `SYS_PTRACE` is the only capability added back:
gdb and `frida -f` need to ptrace the child they spawn. Frida is supported only as
`frida -f <target>` (spawn/inject into its own child), never attach.

## Known limits

- **HTTP only.** No HTTPS/`CONNECT`, so no TLS interception and no HTTPS targets.
  The proxy resolves names once at generation time; a scope host whose IP changes
  mid-run becomes unreachable (fail closed).
- **afl++ without CmpLog and without `-p`** (v1). ASan fuzzing needs
  `ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:symbolize=0`: the profile sets only
  `detect_leaks=0`, and afl++ aborts on a custom `ASAN_OPTIONS` missing the other
  two.
- **frida**: child spawn only (see above); no attach to arbitrary PIDs.
- **Isolation is namespaces + capabilities, not a VM.** A kernel exploit escapes
  it; it does not contain a malicious target binary at that level. `--network none`
  and the internal network stop network egress, not a kernel bug.
- **Pinned versions**: base image by digest, nuclei 3.11.1 and nuclei-templates
  10.5.1 (both sha256-verified against the release's own checksums file, and the
  templates tarball also against the digest pinned in the Dockerfile, since a GitHub
  archive tarball is regenerable), frida-tools 14.13.0 with every dependency
  hash-pinned in `requirements-frida.txt` (`pip --require-hashes`), `afl++=4.04c-4`,
  `sqlmap=1.7.2-1`. The base toolchain (clang/gcc/gdb/curl/libclang-rt) floats
  within Debian bookworm so security updates apply; pin by snapshot if you need
  bit-reproducible images. The frida hashes cover cp311/manylinux_x86_64 wheels
  only, matching the amd64 nuclei binary the image already requires.
- nuclei runs with `-duc -t /opt/nuclei-templates` (templates baked in); never add
  `-nt` — that is new-templates, not "no templates", and it narrows the scan. `HOME=/tmp`
  keeps config writes off `~/.config` and off the read-only root. A nuclei run that skips
  every probe (closed/filtered port) still exits 0 with a 0-byte output file, so
  `run-web.sh` exits 1 when no request crossed the proxy: a scan of nothing is not
  coverage.
- Nothing here replaces the guard's time/disk budget: `maxSeconds`/`maxDiskMB` are
  enforced by `guard.run_with_budget()`, not by the container.

## Tests

```sh
python3 -m pytest skills/security-review/sandbox -v
```

`test_egress_proxy.py` is pure unit tests (proxy + fake upstream in-process, no
runtime needed) and never skips. `test_sandbox.py` builds the image once and runs
real containers; if no runtime is available or the build fails, those tests are
**skipped** with the reason (never silently passed).

`scripts/validate_report.py` re-runs a finding's `pocVerifyCommand` as a bare argv
list: a wrapper such as `timeout 30 ./poc` or `nice ./poc` is rejected on purpose, since
the PoC itself must be `argv[0]` (the timeout belongs on the executor, not the command).
