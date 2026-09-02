# refactor

Plan then execute a multi-file refactor safely. Investigates first, produces a phased plan
(contracts/types → implementations → callers → tests → cleanup) with per-phase verification
and a rollback plan, waits for confirmation, then executes phase by phase — committing and
verifying as it goes.

## Trigger

`/refactor`, or phrases like "refactor this", "plan this refactor", "restructure across
files", "safely refactor", "sequence this change", "extract/split this module", "migrate this
API".

## Flags

- `--no-commit` — don't commit per phase.
- `--auto` — skip the confirmation gate, execute right after planning.

## What it does

1. Asks target/scope and commit preference upfront (skips if inferable).
2. **Plan**: reads the codebase, maps affected files and dependencies, sequences changes
   safely, attaches a verify command + rollback per phase. Stops and asks to proceed.
3. **Execute**: runs one phase at a time, verifying before moving to the next; commits per
   phase by default. Cleanup phase runs a `ponytail-review` pass over the full diff — dead
   code, near-duplicate logic left after the refactor, unclear names, useless/stale comments,
   speculative abstractions exposed — then a `deep-clean` pass over the same diff (bugs +
   code smells, find → fix → rescan until clean), and folds the fixes in before committing.
4. Returns a terse summary: phases done, deviations, skipped items, commit count.

## Files

- `SKILL.md` — the skill instructions.
- `references/verify-commands.md` — stack-detection table for build/test commands per phase.
