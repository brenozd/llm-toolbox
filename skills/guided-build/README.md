# guided-build

Goal-first, checkpoint-driven build process. Interviews the user to surface the real goal and the core decision the project drives, decomposes work into agile buckets, executes them one at a time — each with a plan, implementation, tests, docs, and a user-facing verification checkpoint before moving on.

## Trigger

`/guided-build`, or phrases like "guided build", "interview me first", "build incrementally", "break this into buckets", "plan before you code", "checkpoint-driven", "agile build", "let's plan this together".

## What it does

1. Silent context recon: memory, CLAUDE.md, codebase stack, recent git history.
2. Interviews the user to surface the real goal and key decision.
3. Proposes a decomposition into buckets.
4. Executes bucket by bucket: plan → implement → test → docs → checkpoint with user.
5. Surfaces key decisions explicitly instead of inferring them.
