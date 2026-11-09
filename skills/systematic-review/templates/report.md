# <Review title>

**PRISMA-informed, not PRISMA-compliant.** This review follows the spirit of PRISMA 2020 and PRISMA-S: the flow counts and search reporting are produced mechanically, but the full 27-item checklist was not completed, items were not independently audited, and the protocol was **not registered**. Read it as a transparent LLM-assisted literature review, not as a certified systematic review.

Model / prompt files: <model ids for screening, extraction, appraisal>  ·  `sr.py` version: <metadata.version from SKILL.md>  ·  Review dir: `reviews/<slug>/`

## 1. Question
<one sentence; PICOC from protocol.md §2>

## 2. Method (as run)
- Sources: <OpenAlex, S2, Europe PMC, arXiv, web domainFilter list>. Strings and dates: `search-log.md`.
- Dedupe: `sr.py dedupe` (normalised DOI → normalised title), `study_id` links multiple reports of one study.
- Screening: two-pass LLM screening at title/abstract and full text (passes A and B, same model family, separate files), then **mandatory human arbitration** of every disagreement; exclusions carry reasons.
- Extraction / appraisal: one researcher per shard, second researcher on a <n>% sample; unreadable full text recorded as `TBD: no full text`.
- Snowballing: `sr.py cites` back/forward, ≤2 iterations, DOI-bearing included papers only.
- Synthesis: narrative/tabulated. **No meta-analysis** — no pooled estimates, no kappa.

## 3. Flow counts (verbatim from `sr.py prisma reviews/<slug>`)
| Stage | n |
|---|---|
| Identified (per database, returned/total: <openalex n/n / s2 n/n / epmc n/n / arxiv n/n / web n>) | |
| Duplicates removed | |
| Screened (title/abstract) | |
| Excluded at stage 1 | |
| Sought for full text | |
| Not retrieved | |
| Full text assessed | |
| Excluded at stage 2 | |
| **Included (records / studies)** | <n records / n studies — `counts.included` / `counts.included_studies`> |

`balanced: true` on the last run — <paste run_at>. Stage-2 exclusion reasons: <reason: n, …>.

## 4. Findings by RQ
### RQ1 — <...>
<Answer in prose. Every claim cites a study by first author, year and DOI from the verified list. Thin or contradictory evidence is stated as such.>
### RQ2 — <...>

## 5. Quality appraisal summary
<Counts of high/medium/low, and what they change about confidence. Appraisal does not adjust any number — there is no pooled statistic to adjust.>

## 6. Limitations
- **PRISMA-informed, unregistered.** No PROSPERO/OSF entry, no full checklist, no external audit.
- **Correlated screening errors.** Passes A and B are the same model family, so agreement overstates reliability; the arbitrating human sees only disagreements, and shared blind spots stay invisible.
- **Sensitivity is <estimated at x% from the <n>-record spot-check of stage-1 excludes | unmeasured — the spot-check was not run>.** A single-digit sample bounds nothing tightly; treat missed papers as likely.
- **Coverage bias.** <n> sources and a per-source limit of <n>; non-English, non-DOI and paywalled work is under-represented; web results depend on an opaque, non-reproducible engine and a pre-specified domain list.
- **Snowballing is Semantic-Scholar-only and DOI-only** — grey literature and DOI-less work are not snowballed, so the citation closure is partial.
- **Extraction is model-generated** from full text, sampled-rechecked at <n>%; field-level error remains possible. Appraisal is a checklist, not a risk-of-bias tool.
- **Publication bias not assessed** (no funnel plot, no trim-and-fill).

## 7. Verified references
Only IDs that `sr.py verify` (or a registered `source_check`) resolved to OK, logged in `verified.json`.

| # | Citation | DOI / URL | verified.json entry |
|---|---|---|---|
| 1 | <Author (Year). Title. Venue.> | <10.xxxx/...> | <"id": "...", "ok": true, "title_similarity": 0.xx> |

## 8. End-check
- [ ] Every DOI/URL appearing anywhere above is present in `verified.json` (grep each against the file; zero misses).
- [ ] No citation was added from memory or from an unverified search snippet.
- [ ] Counts in §3 match the last `sr.py prisma` output (`balanced: true`).
- [ ] `sr.py screen-diff` % agreement and the arbitration outcome are recorded in §2 (`unarbitrated_ids: []`).
- [ ] Deviations listed in `protocol.md` §12, none applied silently.

## 9. Declarations
Funding: <none | funder + grant>. Competing interests: <none declared | ...>. Registration: unregistered.
