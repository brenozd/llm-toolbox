---
name: deep-clean
description: >
  Iterative find-and-fix sweep: scans codebase or diff for bugs, security vulnerabilities,
  bad practices, and code smells — then plans, asks for technical decisions, implements fixes,
  rescans, and repeats until clean. Returns a terse summary of all changes made.
  Use whenever the user says: "fix issues", "sweep codebase", "find and fix bugs",
  "review and fix", "hunt bugs", "find bugs", "/deep-clean", "deep clean", "deep review",
  "iterate until clean", "find vulnerabilities and fix", "clean up the code", "audit and fix",
  "fix codebase", "sweep for bugs". Invoke even when the user doesn't say "sweep" — if they
  want issues found AND fixed in one shot, this is the skill.
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash
  - Agent
---

# deep-clean

Scan → triage → fix → rescan. Runs until clean. Terse output throughout.

## Init

Ask upfront (combine into one message):

1. **Scope** — diff/branch only, or full codebase? (`--scope <path>` to limit subtree)
2. **Commits** — one commit per fix, or leave uncommitted? (`--no-commit` to skip)
3. **Mode** — fix or report only? (`--dry-run` to report without editing)

---

## Scan

### Tooling — detect and run all available checks

```bash
ls package.json Cargo.toml go.mod pyproject.toml pom.xml 2>/dev/null
```

| Stack | Commands |
|---|---|
| Python | `ruff check .`, `mypy .`, `pytest --tb=short` |
| JS/TS | `npx tsc --noEmit`, `npx eslint .`, `npm test` |
| Go | `go build ./...`, `go vet ./...`, `go test -race ./...`, `staticcheck ./...` |
| Rust | `cargo check`, `cargo clippy -- -D warnings`, `cargo test` |
| Java/Kotlin | `./gradlew check` or `mvn verify` |
| Generic | `make check`, `make lint`, `make test` |

Run project scripts first — they encode project-specific rules.

### Manual review — what tooling misses

**Logic & implementation**
- Swapped args of same type · inverted conditions (`!x` vs `x`) · off-by-one on indices/bounds
- Wrong default/zero value assumed safe · algorithm doesn't match spec/comment
- Missing recursion base case · wrong operator precedence · short-circuit skips side effects

**Undefined behavior**
- Signed integer overflow · out-of-bounds access · null/nil deref before guard
- Use-after-free / use-after-close / use-after-move · uninitialized reads
- Data races · shift by negative or ≥ type width

**Resource & lifecycle**
- Handle (file/socket/DB) not closed on error path · goroutine/async task never joined (leak)
- Timer started, Stop() never called · deferred close swallows error · double-close

**Concurrency**
- Shared mutable state without lock · deadlock: inconsistent lock order
- TOCTOU: check then act without holding lock · channel send/recv blocking behavior ignored

**Error handling**
- Error silently ignored (`_ = err`) · wrong branch after check
- Error wrap loses context · panic in library code · recover swallows without logging

**Numeric & data**
- Overflow before bounds check · lossy cast (float→int, int64→int32) · division by zero
- Float equality with `==` · silent string truncation on fixed buffer

**Security**
- SQL/cmd/LDAP injection via string concat · path traversal in user input
- Hardcoded secrets · insecure random (`rand` vs `crypto/rand`) · missing auth check

**Bad practices / smells** — full catalogue in `references/code-smells.md` (bloaters, change preventers, dispensables, couplers). Quick hits:
- Error swallowing · mutable globals · side effects in constructors
- N+1 queries · unbounded loops over large collections · god functions, deep nesting
- Duplicate logic · dead code · speculative generality · primitive obsession · feature envy · magic numbers

---

## Triage

One line per finding:

```
file:line 🔴 bug: <problem>. Fix: <solution>.
file:line 🔐 security: <problem>. Fix: <solution>.
file:line 🟡 risk: <problem>. Fix: <solution>.
file:line 🔵 nit: <problem>. Fix: <solution>.
```

- 🔴 **bug** — wrong behavior, crash, data corruption, UB, resource leak, concurrency bug
- 🔐 **security** — exploitable or leaks sensitive data
- 🟡 **risk** — won't crash today but likely to cause problems
- 🔵 **nit** — bad practice, smell, minor inefficiency

Group highest severity first. Skip findings where the fix is obviously wrong for this codebase.

---

## Plan & decision gate

1-line fix intent before touching each file.

**Pause and ask clearly (drop terse style)** when fix involves:
- Multiple valid architectural approaches
- Perf vs safety / simplicity vs extensibility tradeoff
- Breaking change to public API or interface
- DB schema change or migration
- Adding/removing a dependency
- Business logic you don't fully understand

Everything else: fix without asking.

---

## Fix

Order: 🔴 → 🔐 → 🟡 → 🔵.

- Minimal change — no drive-by refactoring
- Verify single-file after each fix before moving on
- One commit per fix (if commits on):

```
fix(<scope>): <what was wrong and what was done>
```

| Type | Commit prefix |
|---|---|
| Bug, logic, UB, leak, concurrency | `fix` |
| Lint error (real mistake) | `fix` |
| Security | `fix` (add `SECURITY:` to body) |
| Unused import / dead code | `chore` |
| Lint (style only) | `style` |

Never combine unrelated fixes. Never suppress linter without comment explaining why. Never modify tests to make them pass — fix the source.

After every 3–5 fixes, re-run the full check suite — fixes expose new issues.

---

## Rescan

After all fixes: run full scan again (tools + manual review of changed areas).

New findings → back to Triage. Clean → Summary.

---

## Dry-run output (`--dry-run`)

No edits, no commits. Report only:

```
file:line 🔴 bug: <problem>.
file:line 🔐 security: <problem>.
file:line 🟡 risk: <problem>.
file:line 🔵 nit: <problem>.

Total: N findings across N files. No changes made.
```

---

## Summary

```
## Sweep complete

### Fixed
- 🔴 <file>: <what>
- 🔐 <file>: <what>
- 🟡 <file>: <what>
- 🔵 <file>: <what>

### Decisions
- <question> → <choice>

### Skipped / deferred
- <item>: <why>

Iterations: N  Commits: N
```

No praise. No filler.
