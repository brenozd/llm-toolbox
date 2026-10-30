---
name: guided-build
description: "Goal-first, checkpoint-driven build: interviews you for the real goal, splits work into buckets, and verifies each with you before moving on. Use for: \"guided build\", \"interview me first\", \"break this into buckets\", \"plan before you code\", /guided-build."
---

# guided-build

Context-first → propose → confirm → execute bucket by bucket, with checkpoints.

---

## Phase 1 — Context Reconnaissance (silent, before asking anything)

If the goal is large or ambiguous (many open decisions, not just 2 unknowns), run the `grilling` skill after the recon below instead of the 2-question limit, then build the Goal Summary from its answers.

Before presenting anything to the user, do the following silently:

**1. Read available context:**
- Check memory files (MEMORY.md + any linked memories) for project history, prior decisions, known constraints
- Check CLAUDE.md for project conventions
- Scan codebase: `find . -maxdepth 3 -name "*.mod" -o -name "package.json" -o -name "go.mod" -o -name "Cargo.toml" -o -name "pyproject.toml" -o -name "*.proto" | head -20` to identify stack
- Check git log (`git log --oneline -10`) for recent work direction
- Read any relevant config files, README, or entrypoints near the working directory
- If the user passed args to the skill, treat them as the raw goal statement

**2. From that context, pre-fill a draft Goal Summary:**

For each field, assign a confidence: `✓ inferred` (high confidence from context) or `? needs input` (genuinely unknown).

Fields to pre-fill:
- **Problem**: What does the request solve? Infer from args + codebase domain.
- **Core decision**: What action or choice does this unlock? Infer from the problem.
- **Success criteria**: What would "done" look like? Propose based on project type (API = endpoint works, CLI = command runs, ETL = data flows through).
- **Constraints**: Stack, conventions, integrations visible in the codebase. Flag any deadlines from memory.
- **Out of scope**: Infer from what the request does NOT mention + what already exists that shouldn't change.

**3. Present the pre-filled proposal (NOT a blank questionnaire):**

Show:

```
## Goal Summary (proposed — correct anything wrong)

**Problem:** <inferred sentence> ✓ inferred | ? needs input
**Core decision:** <inferred sentence> ✓ inferred | ? needs input
**Success criteria:**
  - <proposed criterion> ✓
  - <proposed criterion> ✓
  - ? <blank if unknown — fill this in>
**Constraints:**
  - Stack: <detected: Go 1.21 / Node 20 / Python 3.12 / etc>
  - <any inferred constraints from memory or CLAUDE.md>
  - ? <ask only if a constraint is genuinely unclear and load-bearing>
**Out of scope:**
  - <inferred from what request doesn't mention>
  - <existing systems that shouldn't be touched>
```

Then ask only about `? needs input` fields. If all fields are `✓ inferred`, ask:

> "Does this capture the intent? Say yes to continue, or correct anything."

**Rules:**
- Never ask a blank question when the answer can be inferred.
- Ask at most 2 follow-up questions, only for truly load-bearing unknowns.
- If the user confirms with minor corrections, update the summary inline and proceed.

---

## Phase 2 — Decompose into buckets

Break the work into small, independently deliverable buckets. Rules:
- Each bucket must be completable in one focused session
- Each bucket must have a verifiable output (something you can run, read, or observe)
- Buckets must be sequenced so each one builds on the previous
- No bucket should contain more than one structural decision

**Before proposing buckets**, grep for existing related code:
- Search for files/functions related to the goal to avoid duplicating work
- Note which files will likely need changes (reference them in the bucket table)

Present the decomposition:

```
## Proposed Buckets

| # | Bucket | Deliverable | Key files touched | Depends on |
|---|--------|-------------|-------------------|------------|
| 1 | <name> | <what exists when done> | <path/to/file.go> | — |
| 2 | <name> | <what exists when done> | <path/to/other.go> | 1 |
| … |        |             |                   |            |
```

Ask: "Does this breakdown look right? Reorder, split, or drop any bucket before we start."

Wait for confirmation. Adjust if needed, then confirm the final list before Phase 3.

---

## Phase 3 — Execute buckets (repeat for each)

For each bucket, in order:

### 3a. Plan

Present the plan for this bucket only:

```
## Bucket N: <name>

### What I'll do
- <step 1>
- <step 2>
- …

### Files I'll touch
- <file>: <why — reference actual file paths found in Phase 2>

### Tests I'll write
- <test scenario>: <what it asserts>

### Docs I'll add/update
- <doc location>: <what it covers>

### Key decisions in this bucket
- <decision>: I'll go with <choice> because <reason>. Override?
```

**Decision gate**: For any decision that has real tradeoffs or affects future buckets, stop and ask explicitly. Present options, the tradeoff, and a recommendation. Wait for the user's choice before coding.

Ask: "Ready to proceed with Bucket N? Say go or redirect me."

Wait for go-ahead.

### 3b. Implement

Write the code. Rules:
- Minimal scope — implement exactly what the bucket plan describes
- No refactoring outside the bucket's stated scope
- No speculative features or "while I'm in here" additions

### 3c. Test

Write and run the tests defined in the plan. If tests fail, fix before continuing. Show the test output (or relevant excerpt) to the user.

```bash
# show actual test run output, not a summary
```

### 3d. Document

Update or add documentation as planned. This may be:
- Inline comments where the WHY is non-obvious
- README updates for user-facing behavior changes
- Docstrings for public interfaces
- ADR / decision note if a significant architectural call was made

### 3e. Verify

Run the system or relevant integration check to confirm end-to-end behavior, not just unit correctness. If this project has a CLI, server, or pipeline — run it and observe the output.

### 3f. Checkpoint

Present the bucket's output:

```
## Bucket N Complete — Checkpoint

### What was built
<2–4 bullet summary of what exists now>

### Test results
<pass/fail counts or key assertion output>

### Docs added/updated
<file or section: one-line description>

### Verified by
<what was run and what the result confirmed>

### Decisions made
- <decision> → <choice>

### Drift check
Original goal: <restate from Goal Summary>
Are we still on track? <yes/concern: ...>
```

Ask: "Ready for Bucket N+1, or do you want to revisit anything in this bucket?"

Wait for confirmation before the next bucket.

---

## Phase 4 — Final review

After the last bucket:

```
## Build Complete

### Delivered
<one line per bucket: what it added>

### Decisions log
<all key decisions and choices made across all buckets>

### Outstanding items
<anything deferred, not implemented, or flagged for follow-up>

### Drift check
Original goal: <from Goal Summary>
Core decision enabled: <from Goal Summary>
Confidence this was achieved: <high / medium / low + reason>
```

Ask: "Is there anything left to address, or are we done?"

---

## Rules that apply throughout

- **Context first, questions second.** Never ask what can be inferred from memory, codebase, git log, or CLAUDE.md.
- **Propose, don't interrogate.** Show a filled-in draft; ask only about `?` fields.
- **Never drift silently.** If something you discover mid-implementation changes the plan, stop, report it, and confirm the new direction before proceeding.
- **Decision gate is mandatory** for: architectural choices, breaking changes to interfaces, adding/removing dependencies, DB schema changes, business logic you're uncertain about.
- **Everything else**: implement without asking — don't slow the user down with low-stakes questions.
- **No half-built buckets.** If you can't complete a bucket, stop and explain why — don't deliver partial work as complete.
- **Keep compressed/terse style off** during decision questions and checkpoints. Write clearly when the user needs to make a call.
