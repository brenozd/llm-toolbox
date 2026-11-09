# Search log — <review slug>

Follows PRISMA-S. One row per executed search, appended immediately after the run — never reconstructed afterwards.

## Interfaces
| Source | Interface / API | Version or endpoint | Auth |
|---|---|---|---|
| OpenAlex | `sr.py search --db openalex` | api.openalex.org/works | mailto (`SR_EMAIL`) |
| Semantic Scholar | `sr.py search --db s2` | Graph API /paper/search | optional `S2_API_KEY` |
| Europe PMC | `sr.py search --db epmc` | REST search | none |
| arXiv | `sr.py search --db arxiv` | export API | none |
| Web | `web_search` + `domainFilter` | <provider/model as run> | — |

## Academic searches
| # | Date | Source | Facet | String — copied exactly as run | Filters / limits | total | returned | File |
|---|---|---|---|---|---|---|---|---|
| 1 | <YYYY-MM-DD> | openalex | <facet> | `<string>` | from=<year>, no lang filter, limit=<n> | | | `search/openalex-<facet>.json` |
| 2 | | s2 | | `<string>` | limit=<n> | | | `search/s2-<facet>.json` |

`total` = hits the source claims; `returned` = records actually retrieved. Both are needed; the PRISMA "identified" count uses `returned`.

## Web / grey literature
| # | Date | Query | Domain filter | Results kept | Notes |
|---|---|---|---|---|---|
| 1 | | `<query>` | `<domain1>,<domain2>` | | access date, engine variability |

## Limits and stop rules
- Per-source limit: <n>. Retrieval depth is a limit on coverage, not a quality judgement.
- arXiv calls are serialised (≥3 s apart, global lock) — runs are slow on purpose, do not parallelise them.
- Searches stopped on <date>; anything published later is out of scope.

## Dedupe
`sr.py dedupe search/*.json --out records.csv` → identified <n>, duplicates removed <n>, unique <n>, studies <n>, near-duplicate pairs <n> (listed and reviewed by the user). Method: normalised DOI, else normalised title (similarity ≥ threshold), linked `study_id`.

## Seed recall
Seeds <n>; retrieved <n> → recall <x%>. <gate passed | string refined on <date>, see amendments>.

## Engine variability disclosure
`web_search` is not reproducible: result order, hit counts and index coverage change between runs and are chosen by a third-party model. Web hit counts are therefore not comparable across runs and are never summed into the PRISMA identified total as if they were a database export.

Last search date: <YYYY-MM-DD>.
