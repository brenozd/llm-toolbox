# Protocol — <review title>

Status: **unregistered** (no PROSPERO/OSF entry; review is LLM-assisted, PRISMA-informed — see report).
Frozen after user confirmation on <date>. Every later change goes in **Deviations / amendments**, never edited in place.

## 1. Background
<2-4 sentences: the practice, the uncertainty, why a review now.>

## 2. PICOC
| Element | Value |
|---|---|
| Population | <who/what is affected> |
| Intervention | <technique, tool, practice> |
| Comparison | <baseline, alternative, or "none"> |
| Outcome | <measured or observed outcomes> |
| Context | <domain, language, years, setting> |

## 3. Research questions
- RQ1: <...>
- RQ2: <...>
- RQ3 (optional): <...>
Each RQ maps to ≥1 extraction field (§8) and to a section of the report.

## 4. Sources and search strings
Academic, via `sr.py search` (OpenAlex, Semantic Scholar, Europe PMC, arXiv):

| Source | Facet | String — copied exactly as run | Limit | Date | total/returned |
|---|---|---|---|---|---|
| openalex | <facet> | `<string>` | <n> | <YYYY-MM-DD> | <total>/<returned> |
| s2 | <facet> | `<string>` | <n> | | |
| epmc | <facet> | `<string>` | <n> | | |
| arxiv | <facet> | `<string>` | <n> | | |

"Copied exactly as run" means the literal string, including boolean operators and field tags — no tidying after the fact.

Technical/grey literature, via `web_search` with `domainFilter` — pre-specified domain list:
`<domain1>`, `<domain2>`, `<domain3>` (change to this list = amendment).
The search engine is a black box: ranking, index coverage and result counts vary by run and are not reproducible. That variability is disclosed in the report's limitations; do not compare raw hit counts across runs.

### Seed papers and recall check
Seeds (known-relevant, not used as evidence):
1. <citation / DOI>
2. <citation / DOI>
3. <citation / DOI>

Recall check: for each seed, does the string retrieve it? `recall = found / seeds`.
**Gap:** <x/y = z%>. Gate: refine the string until recall ≥ 80%; if a seed cannot be retrieved at all, record why.

## 5. Eligibility criteria
### Inclusion
- <population / intervention / outcome match>
- <study type, e.g. empirical study with reported results>
- <language, years, peer-review status>

### Exclusion
- <off-topic by PICOC>
- <wrong study type: editorial, opinion, tutorial-only>
- <duplicate report of a study already included (use study_id)>
- <not retrievable in full text — recorded as `not-retrieved`, not silently dropped>
Every exclusion needs a reason string; unlabelled exclusions are a defect.

## 6. Screening procedure
Two-stage: stage 1 title/abstract, stage 2 full text.
1. Records came from `records.csv` after `sr.py dedupe` (DOI-hash then normalised-title match; linked `study_id` for preprint/published pairs; the near-duplicate list is reviewed by the user, never auto-merged).
2. Each stage is screened by **two passes, A and B**, in separate files (`screening/t1-A.csv`, `t1-B.csv`, `t2-A.csv`, `t2-B.csv`). Each pass sees records in a different order and never sees the other's file.
3. A and B are the **same model family** — this is two-pass LLM screening, **not** independent human review. Their errors are correlated.
4. `sr.py screen-diff A.csv B.csv` yields counts, % agreement and the disagreeing ids. Those go to `disagreements.md`.
5. **Human arbitration is mandatory**: the user (not a model) rules on every disagreement and signs the merged `t2.csv`. There is no LLM tiebreaker.
6. Before stage 2, the user spot-checks a fixed random sample of <20> stage-1 excludes (false negatives are the expensive error). Result: <n confirmed / n overturned> → stage-1 sensitivity <measured x% | unmeasured>.
7. "Include if either pass says include" only for advancing to stage 2; the final include set is the arbitrated one.

## 7. Data extraction
One record per study (keyed by `study_id`) into `extraction.csv`, shards of ≤10 papers, one researcher per shard. Fields: <cite the template's fields>. Unreadable or absent full text → `TBD: no full text`, never a guess. A second researcher re-extracts a <10>% sample; discrepancies are logged in `disagreements.md`.

## 8. Quality appraisal
`appraisal.csv`. Academic papers: Kitchenham-style checklist; grey literature: Garousi-style criteria (authority, accuracy, date, objectivity). Checklist wording copied from the source publication, not paraphrased. Appraisal is done by a researcher other than the extractor, on the same shards, and a <10>% sample is re-appraised. Appraisal results feed the synthesis (they weight no numbers; there is no meta-analysis).

## 9. Synthesis statement
**Narrative/tabulated synthesis only — no meta-analysis, no pooled effect size, no kappa.** Counts come from `sr.py prisma`; RQ answers are supported by named studies and quoted findings from `extraction.csv`, with appraisal judgements attached. Heterogeneity in population/outcome is reported descriptively. Where the evidence is thin or contradictory, the report says so instead of averaging.

## 10. Snowballing
`sr.py cites --dir back|fwd` on included papers with DOIs, capped at **2 iterations**; log per iteration which source was used and why iteration stopped ("no new records"). Coverage bias: DOI-only, S2-indexed, English-skewed — declared in limitations.

## 11. Anti-hallucination
A DOI/URL may appear in `report.md` only if `sr.py verify` (or a registered `source_check`) returned OK and wrote it to `verified.json`. Unverified claims are deleted, not softened. The report ends with the end-check that every DOI/URL in it appears in `verified.json`.

## 12. Deviations / amendments
| Date | Section | Change | Reason |
|---|---|---|---|
| | | | |

## 13. Funding
<None, or funder + grant. State "no external funding" explicitly.>

## 14. Competing interests
<"None declared", or the interest. Applies to the human operator and to the tooling (model provider).>

## 15. Registration
Unregistered. No PROSPERO/OSF entry was created; the protocol was not publicly deposited before searching. This is a stated limitation of the report, not an oversight to be smoothed over later.
