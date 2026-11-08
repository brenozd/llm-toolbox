# ASan, AFL++ and triage (binary-c profile)

Everything here runs inside:

```bash
skills/security-review/sandbox/run-c.sh ./work -- bash -lc '<cmd>'
```

No network, read-only root, `/work` is a 512 MB tmpfs with `exec`, host `./work` is
mounted at `/out`, only `SYS_PTRACE` is added back (gdb / `frida -f`).

## Build

```bash
clang -fsanitize=address -g -O0 -fno-omit-frame-pointer -Wall -o target src.c
```

- `-g -O0` keeps frames and variable names; `-fno-omit-frame-pointer` keeps usable stacks.
- Apply the same flags to the fixed twin used as the negative control.
- A prebuilt binary with no symbols: still runnable, but a report without a source
  location is weak evidence. Build from source when it exists.
- For a library/daemon, add a tiny harness `main()` that reads the input file and calls
  the parser, so the PoC has a stable argv.

The container proves the *class* of the error, not its source line: the image ships
`asan_symbolize` but no `llvm-symbolizer`, so in-container traces are addresses only
(`#0 0x55fc40fc68e6 (/out/vuln+0x8e8e6)`, plus `invalid path to external symbolizer`).
`file:line` shows up only when the binary is built and run on the host, or symbolized
offline from the dumped trace. Without `-g` frames are addresses even on the host.

## Run and read the trace

```bash
cd /out && ASAN_OPTIONS=detect_leaks=0 ./target "$(cat input/overflow.txt)"
```

Acceptance line:

```
==12345==ERROR: AddressSanitizer: stack-buffer-overflow on address ...
```

The first frame after the interceptor is a PC — `#0 0x55fc40fc68e6 (/out/vuln+0x8e8e6)`
in the container, `in copy_name vuln.c:8:5` only for a host build with `-g` *and* a
working `llvm-symbolizer` (without one, as observed on this host, frames stay raw PCs).
Keep the whole stderr as evidence; quote nothing from it into free text, never make an
`expect`/assert depend on `file:line`, and take a finding's `location` from the source.

Exit status is not a contract: ASan may abort (134), or die on SIGPIPE when a pipe
closes. Use `expect.stderrContains` on the class string, not `exitCode`.

## Fuzzing (v1 policy: no CmpLog, no `-p`)

```bash
AFL_USE_ASAN=1 afl-clang-fast -g -O0 -o target src.c
mkdir -p in && printf 'seed\n' > in/seed
ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:symbolize=0 \
  afl-fuzz -i in -o out -m none -t 1000 -- ./target @@
```

- `AFL_USE_ASAN=1` adds the sanitizer at compile and link; passing
  `-fsanitize=address` explicitly works too.
- `-m none` is required: ASan reserves a huge shadow mapping and the default memory
  limit would kill the target.
- `ASAN_OPTIONS` must include all three: the profile sets only `detect_leaks=0`, and
  AFL++ refuses to start when a custom `ASAN_OPTIONS` lacks `abort_on_error=1` and
  `symbolize=0`.
- **No CmpLog** — v1 policy, not a tool limit: AFL++ 4.04c in the image implements
  CmpLog (`-c` / `-l`); this profile just runs the plain build. Inputs guarded by
  `memcmp`/magic values will be slow to reach; seed the dictionary (`-x`) instead.
- **No `-p`** — v1 policy: only the default power schedule, though AFL++ offers others.
- Crashes land in `out/default/crashes/`, queue in `out/default/queue/`.

Minimize before writing the PoC:

```bash
afl-tmin -i out/default/crashes/id:000000* -o input/crash -m none -- ./target @@
```

## gdb

```bash
gdb -q -batch -ex 'run' -ex 'bt full' -ex 'info registers' --args ./target "$(cat input/overflow.txt)"
```

For a crash file used as an argument, `run "$(cat input/crash)"` inside the batch
script. gdb needs the `SYS_PTRACE` the profile grants; it is for the child it spawns.

## frida

Only child spawn is allowed:

```bash
frida -f ./target -l hook.js --no-pause
```

`frida -p <pid>` / attach to an arbitrary process is outside the profile and will fail
under the sandbox. `hook.js` should only observe (exports, `strcmp`, allocation sizes);
writing a hook that alters control flow turns triage into exploit development.

## Triage checklist

1. Re-run the input twice; same class and same top frame both times → stable.
2. Compare against the fixed build: the signal must disappear.
3. Classify only the sanitizer class (`stack-buffer-overflow`, `heap-use-after-free`,
   `global-buffer-overflow`, `SEGV on unknown address`, ...).
4. Distinguish *bug* from *harness*: input read past a buffer the harness itself
   allocated is still the target's bug only if the parser wrote/read it.
5. Check whether the input is reachable from a real entry point (file format, CLI arg,
   socket read). A crash only reachable from a debug-only path is low confidence.
6. Do not claim exploitability (RCE/LPE) from a sanitizer abort; that needs its own PoC.
