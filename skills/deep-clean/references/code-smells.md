# Code smell catalogue

Manual-review checklist for the Triage phase. A smell is not a bug — it's a
structural weakness that makes bugs and change harder. Flag as 🔵 nit unless it
actively hides a 🔴/🟡 (then raise severity). Fix only when the fix is local and
low-risk; a smell needing a wide refactor goes to Skipped/deferred with a note,
or hand it to the `refactor` skill.

## Bloaters — code that grew too large

- **Long function** — does more than one thing; can't summarise in a sentence. Extract.
- **Large class / module** — too many fields/methods/responsibilities. Split by axis of change.
- **Long parameter list** — 4+ params, or booleans selecting behaviour. Introduce a param object / split the function.
- **Primitive obsession** — money as float, dates as strings, tuples/dicts standing in for a type. Introduce a small type.
- **Data clumps** — the same 3+ values passed around together everywhere. Bundle them.

## OO / structure abusers

- **Switch/if-else on a type tag** repeated in several places — polymorphism or a dispatch table.
- **Temporary field** — a field set only in some flows, null the rest of the time.
- **Refused bequest** — subclass ignores or overrides most of the parent.
- **Alternative classes with different interfaces** — two things doing the same job, incompatible signatures.

## Change preventers — one change forces many edits

- **Divergent change** — one module edited for many unrelated reasons. Split it.
- **Shotgun surgery** — one conceptual change touches many modules. Consolidate.
- **Parallel inheritance / parallel hierarchies** — every new X forces a new Y.

## Dispensables — pure removal

- **Dead code** — unreachable, unused function/var/param/import, `if False`.
- **Speculative generality** — interface with one impl, hook with no caller, config for a value that never changes, "we might need it" abstraction. (ponytail territory.)
- **Duplicate code** — same logic in 2+ places. Fold into one — but only where this sweep already touches both sites.
- **Comments that restate code** — delete. Stale comments describing old behaviour — delete or fix.
- **Lazy class** — a class/module that no longer earns its keep. Inline it.

## Couplers — modules too entangled

- **Feature envy** — a function that mostly pokes at another object's data. Move it there.
- **Inappropriate intimacy** — two modules reaching into each other's internals / private state.
- **Message chains** — `a.b().c().d().e()`. Hide behind one call.
- **Middle man** — a class that only delegates. Cut out the middle man.

## Common language-agnostic smells

- **Magic numbers / strings** — named constant.
- **Deep nesting / arrow code** — guard clauses, early return.
- **Boolean blindness** — `f(true, false, true)` at the call site. Enum or keyword args.
- **Mutable global / singleton state** — thread it through or scope it.
- **Side effects in constructors / getters / imports.**
- **Inconsistent naming** — same concept, different names across the codebase.
- **God object / manager / util grab-bag** — split by responsibility.
- **N+1 query, unbounded loop over a large collection, work in a hot loop that could hoist.**
- **Error swallowing** — `except: pass`, `_ = err`, empty catch. (Usually 🟡, not 🔵.)
- **Long boolean expression** — extract to a named predicate.
