# Skeletons by page type

Translate headings to the user's language. Drop sections that have no content; never pad.

## Reference (spec, sizing, config)
```
# <Subject>
> <Result in 2-4 lines> · owner · validated YYYY-MM-DD · version
## Summary table            (the answer)
## Fields / items           (same structure per row)
## Rules and formulas       (formula, constants, source)
## Evidence                 (dated snapshot + query/command)
## Assumptions and limits
## Revalidation             (steps + thresholds)
## References
```
Neutral wording. Link to explanation/how-to instead of embedding them.

## Explanation
```
# About <topic>
> The question this answers
## Context and constraints
## How it works            (diagram if it is a flow/topology)
## Alternatives and trade-offs   (include rejected ones, with reason)
## Consequences / when to revisit
## Related                 (links to reference and how-to)
```

## How-to / runbook
```
# <Verb> <object>
> When to use · expected result · duration
## Prerequisites           (access, versions, tools)
## Steps                   (numbered, one action each, expected output after each)
## Verify
## Troubleshooting         (table: symptom | cause | fix)
## Rollback
```
Commands copy-pasteable; no placeholder that fails silently.

## ADR
```
# ADR-NNN: <decision as a sentence>
Status: Proposed | Accepted | Superseded by ADR-MMM · Date · Deciders
## Context                 (forces, constraints, evidence; note expiry of evidence)
## Decision drivers
## Options considered      (each: what, pros, cons, why not)
## Decision                ("We will ..." + rationale)
## Consequences            (positive, negative, obligations created)
```
One decision per record. Never overwrite: supersede with a new ADR.

## Postmortem
```
# <Service> <symptom> YYYY-MM-DD (#id)
Status · Authors · Summary (1 line) · Impact · Trigger · Root cause(s) · Resolution · Detection
## Narrative               (plain language; what was known at each point, wrong hypotheses included)
## Timeline                (UTC table; mark start, mitigated, end)
## Lessons                 (went well | went wrong | got lucky)
## Action items            (action | type prevent/mitigate/process | owner | ticket | status)
## Supporting links        (dashboards, logs, graphs)
```
Blameless: describe systems and information available, not people's faults.

## Worked example: rule vs application
Bad: "Size for worst case (2 cores per 1k jobs/h)", then the 6k tier is justified with 1.1 cores per 1k and no explanation.
Good: "Constant per tier: Small uses worst case 2.0 (customer A, 2026-09-14); Medium uses 1.08 (highest observed at that volume, customer B); Large uses 1.57 (highest observed above 20k jobs/h, customer C). At 2.0 the Large tier would need 50 cores = 78% of 64 vCPU, above the 60% target; this is accepted because ..."
Then verify: `python3 -c` the table, and confirm every tier row matches the stated rule.
