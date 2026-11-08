# Example run — binary-c fixture (acceptance, 2026-11-07)

Honest log of one end-to-end run of `security-review` + `security-review-binary-c`
against `evals/fixtures/binary-c`, played by one agent in two roles: the operator
(harness) who signs the scope, and the reviewing agent that follows the skill.

## Environment

- Host: Fedora, clang/cc/gcc from `/usr/lib64/ccache`, `gdb`, `ssh-keygen`, docker.
- Sandbox image `security-review-sandbox:local` already present (built from
  `sandbox/Dockerfile`); no image build was needed.
- Fixture copied to `/tmp/sr-bin` (repo untouched): `rm -rf /tmp/sr-bin && cp -r
  skills/security-review/evals/fixtures/binary-c /tmp/sr-bin`.
- No `afl-fuzz` on the host (expected); it exists only inside the image.

## Role A — harness (operator)

```bash
ssh-keygen -q -t ed25519 -N '' -C acceptance-harness -f /tmp/sr-keys/scope_ed25519
cat > /tmp/sr-scope/scope.json <<'EOF'
{"targets":["exec://vuln:1"],"expiresAt":"2026-12-31T23:59:59Z",
 "maxSeconds":120,"maxDiskMB":256,"createdBy":"acceptance-harness <harness@example.invalid>"}
EOF
ssh-keygen -Y sign -f /tmp/sr-keys/scope_ed25519 -n security-review-scope /tmp/sr-scope/scope.json
```

Key and public key live in `/tmp/sr-keys`, the manifest in `/tmp/sr-scope`: neither is
in the workspace, and the pubkey is not beside the manifest (guard would refuse it).

## Role B — agent

1. Preflight (`ls` of guard/validator/schema/run-c.sh, `guard.py --help`): OK.
   No `references/asan-afl.md` step was needed — a single seeded flaw, no fuzzing.
2. Stage + build (step 2): `chmod -R a+rwX /tmp/sr-bin` was required first, exactly as
   the skill warns; without it the container (uid 0, `--cap-drop ALL`) cannot write the
   bind mount. Build inside `sandbox/run-c.sh`, not host:

   ```bash
   skills/security-review/sandbox/run-c.sh /tmp/sr-bin -- bash -lc \
     'cd /out && make CC=clang'
   ```

   Result: `vuln` and `fixed` built with `-fsanitize=address -g -O0`, no warnings.
3. Repro (step 3) in the sandbox profile: `./vuln "$(cat input/overflow.txt)"` gives
   `ERROR: AddressSanitizer: stack-buffer-overflow ... WRITE of size 201` (exit 1);
   `./fixed` prints `name too long` (exit 1).
4. Guard run on the host for the recorded repro: same ASan line, exit 1.
5. No minimization/AFL++ (step 5): not needed for this fixture, and the input *is* the
   minimal argv payload. Recorded as not done rather than claimed.
6. PoC (step 6) reused the fixture's `poc_overflow.py` unmodified (sha256
   `4637a80b011b4b15284b5685e761fb259cfacf28cb57c1be164ee285bd1ff784`), argv
   `["/usr/bin/python3","poc_overflow.py","./vuln"]`.
7. Control (step 7): same PoC with `./fixed` → `NO_OVERFLOW`, exit 3. It differs from
   `expect`, which is all the validator checks.

Evidence: `asan.stderr` (full ASan report) and `fixed.stderr` (`name too long`) copied
into `/tmp/sr-evidence`, hashed at validation time:
`51b7c5a4abd7ad2e1caeec8266a64ddc04b94d306ea225db2e2923f28c52a696` and
`79f517a48e9d222d55fb40805db40a8d95b27d30b92e83a3352ca53a31cc4817`.

## Numbers

| item | value |
|---|---|
| findings | 1 (`BIN-OVERFLOW-1`, high, stack-buffer-overflow in `copy_name`) |
| `itemsInspected` | 3 (source review, ASan run, fixed control) |
| validator exit (first accepted run) | 0, `"ok": true`, no errors |
| score exit | 0, `ok: true` |
| score found / missed | 1 / 0 |
| known false positives | 0 (`fixed.c` not reported) |
| unexpected findings | 0 |
| injection markers in report | 0 |
| control run | exit 3, `NO_OVERFLOW` |

Two deliberate harness probes, both refused as intended:
`--target exec://fixed:1` → `guard: target 'exec://fixed:1' is not in the signed scope`
(exit 1); a report whose `negativeControlCommand` also used `./vuln` → validator exit 1
with `the benign control meets expect too, so the expectation proves nothing`.

## Where the skill was wrong or ambiguous

1. **The documented ASan frame is not reproducible.** `SKILL.md` promises
   `#1 ... in copy_name /tmp/sr-bin/vuln.c:8:5`. Inside `run-c.sh` the image has no
   `llvm-symbolizer`, so frames are raw PCs (`(/out/vuln+0x8e8e6)`). On the host, with
   `/usr/bin/llvm-symbolizer` present, the trace is *also* unsymbolized — only
   `SUMMARY: AddressSanitizer: stack-buffer-overflow (/tmp/sr-bin/vuln+0x8e8e6) ...`.
   The class and `WRITE of size 201` are there, the `copy_name` line is not. The
   `location` in the report therefore comes from reading `vuln.c:8`, not from the trace.
2. **The fixture PoC is weaker than the skill's own rule.** `SKILL.md` §4 requires
   `ERROR: AddressSanitizer: <class>`; `poc_overflow.py` accepts any stderr containing
   `AddressSanitizer` (a UBSan/LSan note would satisfy it) and prints the first line
   containing `ERROR`, which need not be the ASan line. The reference PoC pattern is
   stricter; the fixture one wins in practice. I did not edit it (the fixture is the
   eval target), but the validator cannot tell the difference — `expect` is only
   `exitCode 0` + `OVERFLOW_CONFIRMED`.
3. **Evidence has no defined provenance.** The validator re-executes the PoC but offers
   no way to capture that run's output; it only hashes files under `--evidence-dir`. The
   evidence here came from a separate sandbox run with a shell redirect, so its hash
   attests the file, not the validator's execution. Nothing in the skill says how the
   two are tied together.
4. **`itemsInspected` is undefined.** The validator only requires it to be a non-negative
   int equal to `len(coverage.inspected)`; what counts as one "item" (file, run, code
   path) is not specified. Counted as 3 above.
5. **`exec://` conflicts with the schema's wording.** `scope_schema.json` calls every
   target an endpoint and its pattern demands `host:port`; the sub-skill's
   `exec://<basename>:1` is a naming convention with an inert port. The schema cannot
   express "this string is not dialled", so a signer has to trust prose.
6. **Reference doc contradicts rule 6.** `SKILL.md`'s "Offline eval — host-only" builds
   with `make -C /tmp/sr-bin CC=clang` on the host, while rule 6 says build inside
   `run-c.sh`. I used `run-c.sh`; both paths work, but the doc gives two answers.
7. **Evidence/source separation needs `--cwd`.** Step 1 says keep evidence apart from
   sources, and `--cwd` defaults to the evidence dir; the examples do not show that you
   must pass `--cwd` explicitly when they differ. Without it the PoC resolves against
   `/tmp/sr-evidence` and `pocVerifyCommand` names no existing file.
8. `--max-seconds` CLI vs `maxSeconds` ceiling worked (60 under a signed 120); no
   bug found in guard, validator or schema on this run.

## Honest limits

- The guard authorized the literal `exec://vuln:1`; the PoC then spawned `vuln` itself
  in `--cwd`. Nothing in the guard checked that the process stayed inside the intended
  target — documented in the skill, confirmed here.
- PoC and validator ran on the host as this user; only the build and the raw repro were
  containerized (`--network none`, read-only root). No isolation for the validated run.
- One finding, zero false positives, score 0 is a statement about this fixture's seeded
  flaw, not about any real target.
