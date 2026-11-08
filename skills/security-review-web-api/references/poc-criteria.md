# PoC criteria per class

A finding exists when the PoC, run by a stranger on the same target, produces a signal
the benign control cannot. Everything else is a lead. Signal = exit code + one marker in
stdout (or a bare HTTP status) — never a sentence of explanation.

Marker must come from the **response**, not from the PoC's own `print` before the
request. The validator cannot tell the difference; your reviewer can, and so can the
next person who runs it against a patched target. So pick an `expect` value that can
only appear if the target's answer contained it (the leaked row `LEAKED_SECRET_9f3`,
not the PoC's own `SQLI_CONFIRMED`): a substring the PoC prints before sending anything
passes validator *and* scorer, because both only look for the substring.

## SQL injection

- Proof: the payload changes the result set in a way data cannot — a UNION row that is
  not in the table (fixture: `' UNION SELECT 999,'LEAKED_SECRET_9f3'-- ` returns
  `LEAKED_SECRET_9f3`), a boolean pair that differs (`q=alice' AND '1'='1` vs
  `'1'='2`), or a time delay that reproduces.
- Do **not** count: a 500/driver error alone (that is error-based *evidence*, worth a
  `low`/`info` note at most), a quoted echo of the payload, or a LIKE wildcard hit.
- `expect`: `exitCode: 0` + `stdoutContains: "LEAKED_SECRET_9f3"`; optionally
  `httpStatus: 200` if the PoC prints the status.
- Control: same PoC against the parameterized route — fixture `--safe` →
  `/search-safe` prints `NO_LEAK`, exit 1.
- Trap: `/search-safe` and `/search` answer the same benign query identically. Filing
  both is a false positive (`WEB-FP-PARAM` in `evals/expected.json`).
- Stop at the minimum: one row, one marker. No `--dump-all`, `--os-shell`,
  `--file-read`, `--file-write`, no INSERT/UPDATE/DELETE, no stacked queries.

## Reflected XSS

- Proof: the marker appears in the response **unescaped and in an executable context**
  (`<p><script>alert(1)</script></p>`, or an attribute that closes its string and adds an
  `on*=` handler), with `Content-Type: text/html`.
- Do **not** count: the payload reflected inside `&lt;script&gt;`, in JSON that is served
  as `application/json`, or in an `html.escape()`d body. Fixture `/echo` escapes, so it is
  a false positive (`WEB-FP-ECHO`) — this is the whole reason the route exists.
- `expect`: `stdoutContains` of the exact executable fragment as the server returned it
  (e.g. `<script>alert(1)</script>`), not as you sent it.
- Control: same payload against a route that escapes (or the same route with a
  server-side-encoded variant); it must **not** contain the raw fragment.
- No browser needed for v1; if a browser is what makes it execute, say so in `title` as
  "unexecuted reflection" and downgrade — the PoC is HTTP-level.

## IDOR / broken object-level authorization

- Proof: two identities/objects compared with the same request, e.g. object `A` (yours)
  returns 200 with `A`'s data, object `B` (another principal's) returns 200 with `B`'s
  data using **your** credential. The differing field must be data you could not obtain
  legitimately.
- Unauthenticated variant (missing auth): request without the token returns 200 + body
  instead of 401/403.
- Do **not** count: different status codes with no body, an empty list for `B`, a
  redirect to login, or an ID that simply does not exist (404).
- `expect`: `httpStatus: 200` plus `stdoutContains` of a field unique to `B`.
- Control: same request for the object you *are* allowed to see (or with the token
  removed, if the flaw is missing auth). The control must fail `expect`.
- Never enumerate beyond what the scope authorizes: two ids prove the pattern; a sweep of
  10k ids is a different, unauthorized activity.

## Sensitive-data exposure

- Proof: a specific, non-public value in the response that should not be there — a
  secret key, another user's PII, a stack trace with a credential, `.git/config`,
  `/backup.sql` — with the request that fetched it.
- Do **not** count: version banners, "Server: nginx", verbose errors without a secret,
  directory listing of public assets, or a 200 on a path that returns an SPA shell.
- `expect`: `stdoutContains` of a stable fingerprint of the secret (e.g. prefix
  `sk_live_` + length), not the whole secret — evidence files can carry the redacted
  form; the raw value stays out of `title`/`location`.
- Control: the same request to a sibling path that is public, or without the parameter
  that leaks. Different signal required.
- Redaction: `evidenceFiles` may contain the raw bytes; the JSON envelope may not.

## What the negative control does not prove

`report_schema.json` spells it out: the control proves the PoC's signal differs from a
benign command. It does not prove the PoC contacted the target, nor that the signal
depends on the flaw. A PoC that only prints the expected marker passes validator and
scorer. Countermeasure is on you: marker from the response, control on a path that can
only answer safely (fixture `--safe`), and evidence files with the raw response body.
