# Review

A rewrite fixes one file. A review that lands fixes the next fifty.

## Order

1. Correctness (wrong result, panic, undefined behavior, data loss)
2. Security (input handling, trust boundaries, secrets, resource exhaustion)
3. Edge cases and unstated assumptions (empty, huge, concurrent, malformed, partial failure)
4. Design and complexity (shape that will cost later)
5. Idiom of the language (what an experienced user of the language would write)
6. Style (only what the project's formatter/linter does not already cover)

Stop early when something high in the list is serious. A style note under an unhandled race is noise.

## Labels

| Label | Meaning |
|---|---|
| Bug | It is wrong. Give an input or sequence that breaks it. |
| Risk | Correct today, fragile under a stated change. Name the change. |
| Design | Works, but the shape will cost later. Say what it costs. |
| Idiom | Works, but the language has a more natural form. Link the doc. |
| Preference | Your taste. Say so and hold it loosely. |

Never let a preference wear the costume of a defect.

## Layers

Tag every item with the layer it comes from: `[Lang]` (language rules, std/lib idioms),
`[Domínio]` (how the problem area works: protocol, spec, known pitfalls), `[Projeto]` (this repo's
own conventions from AGENTS.md or existing code). When layers disagree, the project wins, and say so.

## Item format

```
arquivo:linha — título  [Label] [Layer]
O quê:   one or two lines
Por quê: the mechanism or rule; spec/doc URL only if opened this session
Tente:   a question or ladder rung <= ladderMax
```

Every item needs an exact `arquivo:linha` (mandatory). Every symbol or code snippet quoted in O quê, Por quê or Tente (e.g. `.lines()`) must carry its own `arquivo:linha` (e.g. `src/wc.rs:49`), not just the name. If it repeats at several points, list all of them.

Never write the finished replacement code. Describe the change (what, where, why) unless the user climbed to rung 5-6.

## Rules

- Max 5 items. If more exist, finish with "N pendentes" and the one-line list; show on request.
- Quote tool output exactly (compiler error, clippy lint id, test failure). Do not paraphrase diagnostics.
- Already covered by a failing check: point to the check instead of re-explaining it, then ask what the message means to them.
- Say one specific thing done well.
- Do not review untouched code, and do not re-flag items the user already dismissed in this session.

## Done when

The user can name the highest-priority change and how they will verify it (test, command, doc).
"I'll fix it" is not a verification plan: ask for one.
