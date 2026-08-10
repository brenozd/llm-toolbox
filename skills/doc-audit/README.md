# doc-audit

Synchronizes documentation with the current code implementation. Iterates through source files and existing docs, finds gaps and stale content, documents non-obvious behaviors (protocols, edge cases, architectural invariants). Also syncs in-code doc comments (JSDoc, Go doc, docstrings), OpenAPI/proto specs, and CHANGELOG entries.

## Trigger

`/doc-audit`, or phrases like "update docs", "audit documentation", "sync documentation", "align docs with code", "document behavior", "revise documentation".

## Flags

- `--commit` (default on) / `--no-commit` — whether to commit the result.
- `--scope <path>` — limit audit to a subtree.

## What it does

1. Scans source files vs existing docs.
2. Flags missing coverage and stale content.
3. Documents non-obvious behavior.
4. Syncs in-code doc comments and specs.
5. Commits the result (unless `--no-commit`).
