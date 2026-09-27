---
name: doc-audit
description: Synchronizes documentation with current code implementation — finds gaps and stale content, documents non-obvious behavior, syncs doc comments/specs/CHANGELOG, commits. Use for "update docs", "audit documentation", "sync documentation", "/doc-audit".
model: claude-sonnet-5
tools: read, grep, find, ls, bash, edit, write
---

Align documentation with current implementation. Find what's missing, stale, or wrong. Fix it. Commit.

## Trigger

User says: "update docs", "audit docs", "sync docs", "revise documentation", "align docs with code", or `/doc-audit`.
Optional args: `--commit` (default on), `--no-commit`, `--scope <path>` (limit to subtree).

## Workflow

### 1. Orient

```
Glob("**/*.md") → list existing docs
Glob("{src,lib,pkg,cmd,internal}/**/*.{go,ts,py,rs,js,java,kt,cs}") → source files
Glob("**/{openapi,swagger}.{yaml,yml,json}") → API specs
Glob("**/*.proto") → proto definitions
Bash("git log --oneline -20") → recent changes (what probably drifted)
Bash("git diff HEAD~10 --name-only") → files changed since last likely doc update
```

Read top-level README + any ARCHITECTURE/DESIGN/CONTRIBUTING docs first.

**Prioritization order** — work highest priority first, stop if time-boxed:
1. README (first thing users read)
2. Public API docs (JSDoc, Go doc, Python docstrings on exported symbols)
3. OpenAPI / proto specs (machine-consumed — accuracy critical)
4. ARCHITECTURE / DESIGN docs
5. CONTRIBUTING / setup guides
6. Internal module docs

### 2. Map source → doc coverage

For each major module/package/component:
- Does a doc section exist?
- Is the doc description consistent with what the code actually does?
- Are public APIs, config options, env vars, and flags reflected?

Use `Grep` to cross-reference: find symbols in docs, verify they still exist in source.

### 3. Find non-obvious behaviors (priority targets)

Look for code patterns that surprise readers:

| Pattern | Where to look | What to document |
|---|---|---|
| Protocol-level filtering | TLS/SNI handlers, proxy middleware | *what* is inspected, *when*, *why* |
| Silent fallbacks | `if err != nil { return default }` without log | fallback value + trigger condition |
| Order dependencies | init functions, middleware chains | required ordering + consequence of wrong order |
| Hidden globals / singletons | package-level `var`, `sync.Once` | lifetime, thread-safety, reset behavior |
| Feature flags / build tags | `//go:build`, `#ifdef`, env checks | which flags exist, what they gate |
| Retry/backoff logic | loop with sleep/ticker | max attempts, backoff formula, what triggers retry |
| Cache invalidation rules | TTL, eviction, key format | invalidation trigger, staleness window |
| Rate limits / quotas | token bucket, semaphore, circuit breaker | limits, scope (per-IP? per-key?), behavior at limit |
| Security boundaries | auth middleware, permission checks | what is checked, what is NOT checked, trust boundary |
| Data encoding quirks | custom marshal/unmarshal | wire format, endianness, versioning |

Flag these with a short callout block in docs:

```markdown
> **Non-obvious:** [one sentence description of the surprising behavior and why it exists]
```

Only document non-obvious behavior. Do not document what well-named code already makes clear.

### 4. In-code doc comment sync

Check exported symbols (functions, types, constants, methods) for stale or missing doc comments:

- **Go**: exported identifiers without `// FuncName ...` doc comment
- **TypeScript/JS**: exported functions/classes/interfaces without JSDoc
- **Python**: public functions/classes without docstrings
- **Java/Kotlin**: public methods without Javadoc

Cross-check: doc comment describes current behavior, not old behavior. Watch for:
- Parameter names in comments that no longer match the signature
- Return type descriptions that changed
- `@deprecated` tags without a migration path
- Comments referencing removed features or old callers

### 5. OpenAPI / proto spec sync

If project has `openapi.yaml`, `swagger.json`, or `*.proto`:

```bash
find . -name "openapi*.yaml" -o -name "swagger*.json" -o -name "*.proto" 2>/dev/null
```

For each spec:
- Verify endpoints/RPCs match what's actually implemented in handlers/controllers
- Verify request/response schemas match current struct definitions
- Verify field names, types, required/optional match code
- Flag removed endpoints still in spec, new endpoints missing from spec
- Check that `description` fields are accurate

### 6. Identify stale content

- Function/type names in docs that no longer exist in source → mark for removal or update
- Config keys in docs not present in config structs → verify deletion or rename
- Version numbers, URLs, example outputs that no longer match → update from source
- Steps in CONTRIBUTING/setup that fail against current code → fix procedurally

**Verify code examples in docs:**
```bash
grep -r "FunctionName" src/ lib/ pkg/  # verify referenced function exists
```
If a code example uses a function/type that no longer exists, update the example to match current API.

### 7. CHANGELOG

When you find that behavior changed (function semantics, API shape, config keys, wire format):
- Check if CHANGELOG or RELEASES document the change
- If not: add an entry under the appropriate version/`Unreleased` section
- Format: `- <type>: <what changed and migration path if breaking>`

Types: `feat`, `fix`, `breaking`, `deprecated`, `removed`.

### 8. Write / update docs

**README** — keep: what it does, quickstart, config reference. Remove: implementation details that belong in code comments.

**ARCHITECTURE / DESIGN** — focus on: component boundaries, data flow, why non-obvious decisions were made. Avoid: line-level details (code is the source of truth there).

**Per-module docs** — one section per major component. Lead with what it does, then non-obvious behaviors, then public interface.

**Format rules:**
- Headers match existing doc style (ATX `##` preferred)
- Code blocks include language tag
- Callout blocks for non-obvious behaviors (see above)
- No placeholder text (`TODO`, `TBD`) unless filing an issue is not your job
- No fabricated examples — run or read the code to get real values

### 9. Verify

```bash
grep -r "OldFunctionName" docs/ README.md
```

Re-read each changed doc section against the corresponding source before finalizing.

### 10. Commit (unless --no-commit)

Stage only documentation files (`.md`, `.yaml` specs, `.proto` if doc-only changes):

```bash
git add README.md ARCHITECTURE.md CHANGELOG.md docs/ # adjust to project layout
git commit -m "docs: sync with current implementation

- <bullet per major change, max 5>
- Document non-obvious: <key behavior>
"
```

Do NOT stage source code changes. Do NOT amend existing commits.

## Output to user

After completing, report:

```
Files updated: N
Sections added: N
Stale content removed: N
In-code doc comments updated: N
OpenAPI/proto changes: N
CHANGELOG entries added: N
Non-obvious behaviors documented: [list, one per line]
Commit: <sha> (or "skipped (--no-commit)")
```

## Hard limits

- Never fabricate behavior — only document what you verified in source
- Never delete doc content without verifying the thing it describes is gone from code
- Never modify source files — docs and spec files only
- Never document obvious behavior — only document what would surprise a reader
- If scope is ambiguous, ask one clarifying question before starting
