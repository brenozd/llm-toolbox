# bug-sweep

Iterative find-and-fix sweep. Scans codebase (or diff) for bugs, security issues, bad practices, code smells — then plans, asks for technical decisions, implements fixes, rescans, repeats until clean.

## Trigger

`/bug-sweep`, or phrases like "fix issues", "sweep codebase", "find and fix bugs", "review and fix", "hunt bugs", "find bugs", "deep review", "iterate until clean", "clean up the code", "audit and fix".

## Flags

- `--scope <path>` — limit sweep to a subtree instead of the whole repo/diff.

## What it does

1. Asks scope (diff/branch vs full codebase) upfront.
2. Scans for bugs, security vulnerabilities, bad practices, code smells.
3. Plans fixes, surfaces technical decisions that need user input.
4. Implements fixes.
5. Rescans, repeats until clean.
6. Returns a terse summary of all changes made.
