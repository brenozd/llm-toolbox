---
name: wiki-writing
description: "Write or audit dense, verified technical wiki pages (reference, explanation, runbook, ADR, postmortem, sizing/design docs). Use for: \"write a wiki page\", \"escreva um artigo de wiki\", \"revise esta página\", /wiki-writing."
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
---

# Wiki page writing

Write the page in the user's language. Load a `references/` file only when the step says so.

## 1. Before writing
- Pick ONE type: reference (look up facts) | explanation (why) | how-to/runbook (do a task) | ADR (decision) | postmortem (incident). Mixed content: split into linked pages.
- Fix in one line: reader + what the page lets them decide or do.
- Missing input (reader, type, language, sources): ask one short question; if the user already gave it, go straight to writing.
- Collect sources first (code, metrics, tickets, existing pages). Never write numbers from memory. Read the real file/command output; do not trust a pasted summary when the origin is reachable. Missing fact: write `TBD: <what is needed>` and report it. Never invent.
- Read the chosen type's skeleton in `references/templates.md`.

## 2. Skeleton
Title (noun phrase, sentence case) → lead of 2-4 lines (answer first, scope, owner, validated date, version) → body per type → assumptions and limits → revalidation (if data ages) → references as links.

## 3. Style
- Inverted pyramid. One idea per paragraph, at most 4 sentences.
- Active voice; second person for procedures; condition before instruction.
- Every number has unit; measured values have source and date. One term per concept; define it at first use.
- Timeless: avoid currently/now/new/soon/latest (atualmente/agora/novo/em breve/último). Anchor to a date or version instead.
- Dense: facts, thresholds, formulas, commands. Delete any sentence whose removal loses no fact. No marketing, no restating the heading, no closing recap.
- Format: prose for reasoning; numbered list for sequences; bullets for parallel items (one line each, under 60% of the page); table for 3+ attributes per item, introduced by a sentence; code block for commands and queries. Bold only scan-terms (max 1 per paragraph). No emoji.
- Reference pages: neutral, austere, structure mirrors the thing described; opinion goes to an explanation page. Explanation pages: why, rejected alternatives, trade-offs, tight scope.
- Link, don't repeat. Cite as `[Title](URL)`, never "wiki page 90".

## 4. Evidence and consistency (mandatory when the page has numbers or rules)
- Show the calculation or its inputs for every derived number. Cite code or config with exact `path:line`; cite data with query + date.
- Rule and application use the same constants. If an application uses a different value, state which and why.
- Run the arithmetic (Bash/python). Compare each table value with the stated rule. Check that counts match the lead (rows vs "N instances").
- Keep durable method apart from volatile data. Label the snapshot date.
- State assumptions, limits and what was not checked.
- Add how to revalidate: queries/commands plus thresholds that trigger action.

## 5. Visuals
Default: none. Add one only when it carries what words cannot (flow, state, topology, data shape). Decision table and rules: `references/diagrams.md`. Introduce each with a sentence, refer to it as "figure N", write alt text, keep the data table beside any chart.

## 6. Independent review (pages with numbers, rules or decisions)
The author re-checking its own work misses what it already believes. Before delivering, spawn the `devils-advocate` agent when available (otherwise a fresh subagent) with: the page, the sources, the reader and goal. Ask for unsupported claims, rule-vs-table mismatches and missing limits. Fix findings, then deliver. Skip for short pages with no numbers.

## 7. Checklist before delivering
- [ ] One type; lead holds answer, owner, date
- [ ] Numbers: unit, source, date; arithmetic run; rule equals application
- [ ] No filler, promo, timeless violations; terms consistent
- [ ] Links resolve; references listed
- [ ] Each visual justified; alt text present
- [ ] Assumptions, limits, revalidation present

Final reply: 1-2 lines on what was written plus open `TBD`s. No recap.

## References (on demand)
- `references/templates.md`: skeletons per type + one worked example
- `references/diagrams.md`: when to use diagram/chart/table, Mermaid and alt-text rules
- `references/sources.md`: external sources behind these rules (maintenance only; do not load while writing)
