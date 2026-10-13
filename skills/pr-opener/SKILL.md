---
name: pr-opener
description: "Open a pull request for the current branch: verify work, read the PR template, draft title/body, confirm, push, create (draft by default; gh/tea/glab/Forgejo). Use for: \"open a PR\", \"create a pull request\", /pr-opener."
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
  - mcp__forgejo__pull_request_write
  - mcp__forgejo__pull_request_read
---

# pr-opener

Verify work done → gather diff vs base → draft title/body → confirm → push → open PR (draft by default).

## Trigger

User says: "open a PR", "create a pull request", "open PR", "make a PR", or `/pr-opener`.
Optional args: `--no-draft`, `--base <branch>`.

Start the workflow immediately on invoke — no preamble.

## Workflow

### 1. Verify completion

Check conversation/task state for unfinished work (open TODOs, failing tests, uncommitted
changes not yet staged). If something looks incomplete, ask the user to confirm before
proceeding — never silently PR half-done work.

### 2. Gather git context

Run in parallel:

```bash
git status
git rev-parse --abbrev-ref HEAD
git remote get-url origin
```

Then, once base branch is known (step 3):

```bash
git log origin/<base>..HEAD --oneline          # commit list
git diff origin/<base>...HEAD --stat            # changed files
git diff origin/<base>...HEAD                   # full diff — THIS is what the PR body describes
```

**Important:** the PR body must summarize the diff against the base branch (everything that
will land on it), not just the latest local commit or a diff between two recent commits on
the same branch. Use `git log` only for the commit list / narrative, not as the source of
what changed.

### 3. Detect base branch + forge tooling

Base branch: `git remote show origin` (look for `HEAD branch:`), fall back to `origin/main`
then `origin/master`. Let `--base <branch>` override.

Forge: don't hardcode one. Probe in this order, use the first that works:

1. CLI on PATH matching the remote host or generically available: `gh` (GitHub), `tea`
   (Gitea/Forgejo), `glab` (GitLab).
2. Loaded MCP tool: `mcp__forgejo__pull_request_write` if this session has Forgejo MCP tools.
3. No match → push only, then print the remote's compare URL (derive from `git remote
   get-url origin`, e.g. `https://<host>/<owner>/<repo>/compare/<base>...<branch>`) for the
   user to open the PR by hand.

### 4. Read PR template if present

Check, in order: `.github/PULL_REQUEST_TEMPLATE.md`, `.gitea/PULL_REQUEST_TEMPLATE.md`,
`.forgejo/pull_request_template.md`, `PULL_REQUEST_TEMPLATE.md` (repo root), and lowercase
variants. If found, the body MUST follow its structure/sections. If absent, use a plain
default: `## Summary` (bullets, why not just what) + `## Test plan` (checklist).

### 5. Issue-link keyword

Default to `Related to #N`. Only use `Closes #N` / `Fixes #N` if the user explicitly confirms
this PR fully resolves the issue — never assume.

### 6. Draft proposal

Title ≤72 chars, imperative mood. Body per template (or default from step 4), built from the
step-2 diff. Present title + body to the user and wait for approval — do not push yet.

### 7. Push + create

On approval:

```bash
git push -u origin <branch>   # -u only if no upstream tracking yet
```

Then create the PR with whichever tool step 3 resolved, **draft by default**
(`--no-draft` disables):

- `gh pr create --draft --base <base> --title "<title>" --body "<body>"`
- `tea pr create --draft --base <base> --title "<title>" --description "<body>"`
- `glab mr create --draft --target-branch <base> --title "<title>" --description "<body>"`
- `mcp__forgejo__pull_request_write` with draft flag set
- no tool matched → already pushed in this step; print the compare URL from step 3

Print the resulting PR URL.

## Hard limits

- Never push without explicit user approval of the drafted title/body.
- Never force-push.
- Never skip the completion check in step 1.
- Never use `Closes`/`Fixes` without explicit user confirmation.
- Never skip reading the PR template when one exists.
- Never fabricate issue numbers — only reference ones the user or branch/commit messages named.
