---
name: systematic-review
description: "Run a PRISMA-informed, LLM-assisted systematic literature review end to end: protocol, multi-source search, dedupe, two-pass screening with human arbitration, extraction, appraisal, snowballing, synthesis and a citation-verified report. Use when the user asks for a systematic review, literature review with a method, evidence map or PRISMA-style flow, or says: \"systematic review\", \"revisão sistemática\", \"revisao sistematica\", /systematic-review."
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
metadata:
  version: "0.1.0"
---

# Systematic review

Everything lives in `reviews/<slug>/` in the repo cwd (`mkdir -p reviews/<slug>/{search,screening,extraction,fulltext}`) — never `/tmp`: researcher `safe_bash` blocks writes outside the cwd. Plumbing is `sr.py` (stdlib only, JSON on stdout):

```bash
SR=skills/systematic-review/scripts/sr.py; REVIEW=reviews/<slug>
/usr/bin/python3 $SR --version   # metadata.version above; quote it in the report
```

Delegation defaults (`timeoutMs`, `toolBudget`, reviewer brief shape): `skills/guided-build/SKILL.md:12-17` — apply to every child, do not copy them here. Never pass `model` or `thinking` to a child; the session model is the user's choice. One researcher per shard, each returning ≤15 lines and writing files, not answers.

Report language = user's language. Templates: `templates/` (protocol, search-log, screening, extraction, appraisal, report).

## Phase 1 — Protocol (before any search)
- Input: the user's question. Output: `reviews/<slug>/protocol.md` from `templates/protocol.md`.
- Fill PICOC, RQs (each mapped to ≥1 extraction field), sources × search strings, filters, inclusion/exclusion criteria, `study_id` rule, seed papers, pre-declared `web_search` domain list.
- State registration status (**unregistered**), funding, competing interests, and that screening/extraction are LLM-assisted.
- **Gate: the user approves the protocol; then it is frozen.** Later changes go in its *Deviations / amendments* section, never in place.
- Done-check: every RQ has a field and a report section; every criterion is answerable yes/no from title+abstract.

## Phase 2 — Search
- Input: protocol §4. Output: `$REVIEW/search/<db>-<facet>.json` (one file per database × facet; `sr.py search` names the database `--db` and the limit `--limit`).
- Parallel per database, except **arXiv is serialised** (the script's lock enforces its 3 s global gap — do not run two arXiv searches at once).
- ```bash
  /usr/bin/python3 $SR search --db openalex --query "<string>" --limit 100 --out $REVIEW/search/openalex-facet1.json
  ```
  Databases: `openalex`, `s2`, `epmc`, `arxiv`. `S2_API_KEY` raises the S2 quota and `SR_EMAIL` is required by `sr.py oa`; note both in the report if unset.
- Web facet: only the pre-declared domains; disclose that engine ranking varies between runs. Legal sources only — never Sci-Hub/Anna's Archive or any pirate mirror.
- Validate recall: the strings must find ≥80 % of the seed papers, else refine and re-run.
- Output `$REVIEW/search-log.md` (PRISMA-S): interface/version, exact string, filters, date, total vs returned, dedupe method, last-search date.
- Done-check: every facet has a file whose `returned` matches its `records[]` length.

## Phase 3 — Dedupe
- Input: `$REVIEW/search/*.json`. Output `records.csv` + JSON counts: `total`, `returned`, `duplicates_removed`, `near_duplicates`.
- ```bash
  /usr/bin/python3 $SR dedupe $REVIEW/search/*.json --out $REVIEW/records.csv
  ```
- `study_id` links reports of the same study at ≥0.95 title similarity; review the printed `near_duplicates` and merge/separate by hand before screening.
- Done-check: `duplicates_removed = total - returned`; every linked `study_id` group inspected.

## Phase 4 — Retrieval
- Input: `records.csv`. Output `$REVIEW/fulltext/<study_id>.pdf|.txt|.md` plus one `not-retrieved` row per failure in `$REVIEW/screening/not-retrieved.csv`.
- Phase 4 owns `screening/not-retrieved.csv` only; `t1.csv`/`t2.csv` belong to Phase 5. `prisma` reads the retrieval file and the arbitrated files beat it.
- `/usr/bin/python3 $SR oa <doi>` gives open-access locations; otherwise the DOI landing page.
- Done-check: every included-at-stage-1 study is either retrieved or listed as `not-retrieved` (that count reaches PRISMA).

## Phase 5 — Screening (two-pass LLM + human arbitration)
- Input: `records.csv`. Output: `$REVIEW/screening/t1-A.csv`, `t1-B.csv`, then the human-arbitrated `t1.csv`; same for `t2.csv`. Phase 5 is the **single owner of `t1.csv` and `t2.csv`** — no other phase writes them.
- Pass A and pass B are two independent LLM runs **of the same model family** — call it "two-pass LLM screening", never "dual independent reviewers".
- **Merge rule (`sr.py prisma`):** A and B are merged first (include if either pass included, a false negative costs more), then the arbitrated `t1.csv`/`t2.csv` is applied last and **wins** — the human decision is final for every id it lists.
- **What goes in `t1.csv`/`t2.csv`: only the ids the human arbitrated** (the disagreements). `t1-A.csv`/`t1-B.csv` hold every id; the merge rule above fills everything `t1.csv`/`t2.csv` does not list. `t2.csv` must cover every sought id (`include`/`exclude`, or `not-retrieved` via Phase 4's file) — `prisma` balances only then.
- ```bash
  /usr/bin/python3 $SR screen-diff $REVIEW/screening/t1-A.csv $REVIEW/screening/t1-B.csv --arbitrated $REVIEW/screening/t1.csv
  ```
  It compares A vs B and reports `disagreeing_ids` (plus `% agreement`) and `unarbitrated_ids` (disagreements with no row in the arbitrated file); never diff the CSVs by hand.
- **Every disagreement is arbitrated by the human (the user), and logged** with its reason in `t1.csv`/`t2.csv`. No LLM tiebreak. Include on doubt (a false negative costs more).
- Then human-check a **fixed sample of stage-1 excludes** (all of them if ≤20) and record the observed error rate, or "sensitivity unmeasured".
- Done-check: `screen-diff … --arbitrated t1.csv` reports `unarbitrated_ids: []` — every id A and B disagree on has a row in the arbitrated `t1.csv`. Every excluded row has a reason string.

## Phase 6 — Extraction and appraisal
- Input: `t2.csv` includes + full texts. Output: `$REVIEW/extraction/extraction.csv`, `appraisal.csv` from `templates/`.
- One researcher per shard writes the CSV; a second researcher independently re-extracts and re-appraises a sample (≥10 % or 5 studies, whichever is larger); discrepancies are logged and resolved by the human.
- Appraisal rating feeds synthesis; unreadable full text stays `TBD: no full text` — never inferred.
- Done-check: one row per included study, no empty outcome field without a `TBD:` marker.

## Phase 7 — Snowballing
- Input: included DOIs. Output: back/forward hits appended to `search/snowball-<n>-<dir>.json` (db `snowball`), then re-screened.
- ```bash
  /usr/bin/python3 $SR cites <doi> --dir back --out $REVIEW/search/snowball-1-back.json
  ```
- **Re-run Phase 3 dedupe after every snowball round** (`sr.py dedupe $REVIEW/search/*.json --out $REVIEW/records.csv`): hits land in `search/` and would otherwise count as duplicates. `prisma` reports `snowball` apart from the database counts.
- **Cap: 2 iterations.** Log the stop reason and the per-iteration source, and declare the coverage bias (S2 only, DOI-bearing papers only).
- Done-check: cap respected, records re-deduped and re-screened, stop reason written in `search-log.md`.

## Phase 8 — Synthesis and report
- Input: `t2.csv` includes, `extraction/extraction.csv`, `appraisal.csv`, `verified.json`. Output: `$REVIEW/report.md` from `templates/report.md`.
- ```bash
  /usr/bin/python3 $SR prisma $REVIEW   # counts + arithmetic check; copy the numbers verbatim
  /usr/bin/python3 $SR prisma $REVIEW --stage 1   # mid-review checkpoint: checks the stage-1 flow only and exits 0 before `t2.csv` exists
  ```
  A non-zero exit means the flow counts do not add up — fix the review, never the report. `--stage 1` is for checkpoints only; the report needs the full (stage-2) run balanced.
- `included` counts records, `included_studies` counts distinct `study_id` — the report quotes both, and `per_source` (returned) is reported next to `per_source_total` (what each database claimed).
- The report says **PRISMA-informed**: full checklist not completed, protocol unregistered, no pooled estimate, no kappa, no meta-analysis.
- **Anti-hallucination, non-negotiable:** every DOI/URL in the report must come from `verified.json`. Verify each first:
  ```bash
  /usr/bin/python3 $SR verify 10.xxxx/yyyy --title "<as printed>" --out $REVIEW/verified.json
  ```
  Exit ≠ 0 (unresolvable id, or title similarity < 0.90) means the citation is not allowed in the report. End-check: grep the report's DOIs/URLs against `verified.json`, all present, none invented.
- Done-check: `prisma` balanced, every citation verified, model/prompt ids and `sr.py --version` recorded in the header.
