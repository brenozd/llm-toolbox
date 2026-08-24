---
name: refactor
description: >
  Plan then execute a multi-file refactor safely. Investigates the codebase first, produces
  a phased plan (types/contracts → implementations → callers → tests → cleanup) with
  per-phase verification and a rollback plan, waits for confirmation, then executes phase by
  phase committing and verifying as it goes. Use when the user asks to refactor, restructure,
  rename across files, extract/split a module, migrate an API/interface, or otherwise change
  code that touches multiple files. Also triggers on "/refactor", "plan this refactor",
  "safely refactor", "sequence this change".
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash
  - Agent
---

# refactor

Two modes, always in this order: **Plan**, then **Execute**. Never edit files during Plan.

## Init

Ask upfront only if not inferable from the request (combine into one message):

1. **Target** — what's being refactored (module/pattern/API) and why (if it matters for scope).
2. **Commits** — one commit per phase step, or leave uncommitted? (`--no-commit` to skip)
3. **Stop after plan** — default yes. `--auto` skips the confirmation gate and executes immediately.

---

## Plan

1. Search the codebase to understand current state — read implementation, tests, config, docs
   touching the target. Don't guess at call sites; grep for every caller.
2. Identify affected files, ownership boundaries, dependencies, and likely hidden coupling
   (reflection, string-based lookups, generated code, serialization formats).
3. Sequence changes safely. Default order: contracts/types first, then implementations, then
   callers, then tests, then cleanup/dead-code removal. Deviate only if the codebase's actual
   dependency graph demands it — say why. Cleanup phase always includes a ponytail pass (see
   below) — plan for it even on a small refactor.
4. Attach a verification command to every phase — see `references/verify-commands.md` for
   stack detection and per-stack build/test commands — and a rollback step for the riskiest
   phases.
5. Output the plan in the format below. Stop. Ask: **"Shall I proceed with Phase 1?"**

Skip planning ceremony for a single-file, mechanical rename with no external callers — just do it
and say so in one line.

### Plan output format

```markdown
## Refactor Plan: [title]

### Current State
[how it works now, 1-3 sentences]

### Target State
[how it will work after, 1-3 sentences]

### Affected Files
| File | Change Type | Dependencies |
|------|-------------|--------------|
| path | modify/create/delete | blocks X, blocked by Y |

### Execution Plan

#### Phase 1: Contracts / Types
- [ ] Step 1.1: [action] in `file`
- [ ] Verify: [command or check]

#### Phase 2: Implementation
- [ ] Step 2.1: [action] in `file`
- [ ] Verify: [command or check]

#### Phase 3: Callers
- [ ] Step 3.1: [action] in `file`
- [ ] Verify: [command or check]

#### Phase 4: Tests
- [ ] Step 4.1: update tests in `file`
- [ ] Verify: run full test suite

#### Phase 5: Cleanup (ponytail pass)
- [ ] Remove dead code / deprecated paths
- [ ] Reuse: fold near-duplicate logic touched by this refactor into one place instead of
      leaving copies (only where the refactor already touches both — don't go hunting repo-wide)
- [ ] Rename variables/functions left unclear by the refactor (single letters outside tight
      loops, `data`/`temp`/`obj`, names that lie about what the thing now holds)
- [ ] Delete comments that just restate the code, stale comments describing pre-refactor
      behavior, and commented-out old code
- [ ] Flag (don't silently fix) any speculative abstraction the refactor exposed — interface
      with one implementation, config for a value that never changes, unused flexibility
- [ ] Update docs/comments that describe old behavior

### Rollback Plan
1. [step to undo riskiest phase]
2. [step to undo next riskiest]

### Risks
- [risk] → [mitigation]
```

---

## Execute

Only after the user confirms (or `--auto` was passed).

- One phase at a time, in order. Complete every step and its Verify before moving to the next
  phase — a red verify blocks progression; fix or roll back before continuing.
- Minimal diff per step — no drive-by cleanup outside what the plan lists. New findings
  (bugs, unrelated smells) go in the Skipped section of the summary, not into this diff.
- Commit per phase (unless `--no-commit`):

```
refactor(<scope>): <phase N — what changed>
```

- If a phase's verify fails and the fix isn't a 1-liner, stop and report — don't improvise
  around the plan silently.

**Cleanup phase**: before committing it, run the `ponytail-review` skill over the full diff
produced by this refactor (all phases combined, not just Phase 5's own edits) to catch
over-engineering, bad names, useless/stale comments, and reuse misses the other phases
introduced or left behind. Apply its findings as part of this phase's diff; anything you
disagree with or that needs a judgment call goes to Deviations in the summary, not silently
dropped.

---

## Summary

```
## Refactor complete

### Phases done
- Phase N: <what changed> — verified via <command>

### Deviations from plan
- <what changed and why>

### Skipped / deferred
- <item>: <why>

Commits: N
```
