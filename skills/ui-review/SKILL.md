---
name: ui-review
description: >
  Evaluate and improve a web UI against usability, accessibility, performance,
  responsiveness, and visual-consistency frameworks — captures the live page
  (screenshots, console/network) and returns a ranked, tagged finding list
  with concrete fixes. Use whenever the user asks to review, audit, critique,
  or improve a web page or GUI, even if they just say "does this page look
  right?" or "what's wrong with this screen?" — not only when they say "UI
  review" explicitly. Triggers: "avaliar UI", "revisar GUI", "melhorar
  interface", "review this UI", "audit this web page", "/ui-review". Generic
  — works on any web page, not tied to any specific project.
metadata:
  version: "1.1.0"
---

# UI Review

Evaluate a live web page and return a ranked list of findings, each tagged by
category, located as `file:line` (or selector if no source line applies), and
paired with a concrete fix. Not an essay — a checklist run against a real
page, then a short report.

If the project has its own design doc or style guide (design tokens,
existing components, a known-issues log), read it first — don't re-report a
documented decision as a bug, don't re-report a tracked known issue as new,
and prefer "reuse existing token/component X" over "add a new one" as a fix.
If no such doc exists, skip straight to capture.

## 1. Capture the live page

Prefer `claude-in-chrome` — it's already in the running browser, no extra
process to manage. Load its tools with `ToolSearch` first if deferred
(`tabs_context_mcp`, `navigate`, `computer`, `read_page`,
`read_console_messages`, `read_network_requests`), check `tabs_context_mcp`
before opening a new tab, and don't trigger JS `alert`/`confirm`/`prompt` —
they block the extension.

If `claude-in-chrome` isn't connected or isn't available in this session,
fall back to Playwright. Check first whether it's already usable
(`python3 -c "import playwright"` or `npx playwright --version`) — if not
installed, don't install it silently: tell the user it's missing and ask
before adding a new dependency just for one review. If they say yes, or it's
already there, drive it via a short throwaway script: launch a browser,
navigate, screenshot at mobile (375px), tablet (768px), and desktop (1440px)
widths, and capture console errors on load.

Either way, collect:
- screenshots at 2-3 viewport widths (at least mobile + desktop)
- console errors/warnings
- network requests that failed or look unusually large/slow (only if the
  tool surfaces this cheaply — don't build a waterfall analysis by hand)

## 2. Evaluate, tag every finding

Go through each category below. If a category can't be checked (no
Lighthouse/axe installed, no way to measure timing), say so explicitly under
that category instead of silently skipping it — "not measured: no Lighthouse
in this environment" is a valid line, silence is not.

**[heuristic] — usability**
`WebFetch` the live guidelines first:
`https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`
— they're concrete (touch target sizes, loading-state rules, form behavior,
motion) rather than abstract, and stay current since they're pulled fresh
each run. Apply every rule that fits what the page actually is; an internal
single-user tool doesn't need onboarding copy, a public form does.

If the fetch fails or is unavailable, fall back to
`references/nielsen-heuristics.md` and note in the report that the live
guidelines weren't reachable.

**[a11y] — WCAG 2.2 AA**
Check against `references/wcag-checklist.md`: color contrast (compute the
ratio, don't eyeball it), keyboard navigation and focus order, ARIA where
native semantics don't cover it, alt text, touch target size, reflow at
narrow widths.

**[perf] — Core Web Vitals**
LCP < 2.5s, CLS < 0.1, INP < 200ms. Measure via Lighthouse or a Playwright
CDP trace only if already installed. If not, note qualitatively from what's
observable — large unoptimized images, visible layout shift on load, an
obviously slow network waterfall — and say the numbers weren't measured.

**[responsive] — layout across widths**
Compare the mobile/tablet/desktop screenshots directly: horizontal scroll
that shouldn't be there, text or controls clipped/overlapping, a breakpoint
that leaves an awkward in-between layout, touch targets that shrink below
the a11y minimum on narrow widths.

**[visual] — consistency**
Compare against the project's own design tokens/components if a design doc
exists (see intro); otherwise judge internal consistency of the page itself —
spacing scale, color palette, repeated one-off components that should be one.

**[state] — error/empty/loading handling**
What does this page show with zero data, mid-request, and after a failed
request? A blank screen or a stuck spinner is a finding.

## 3. Report format

Ranked most-severe first. One line per finding, `file:line` when the finding
maps to source, otherwise a selector or short location description:

```
[category] file:line — what's wrong
  fix: concrete suggested change
```

Example:

```
[a11y] style.css:42 — button.primary white text on --accent is 3.22:1, below AA's 4.5:1 for normal text
  fix: darken --accent or swap button text to --text

[heuristic] bulk_ops.html:118 — Enter key in the LIMIT field submits nothing, no visible feedback
  fix: bind the same handler as the Run button, or disable the field until a query is loaded

[responsive] header nav (375px) — logo and menu button overlap below 400px
  fix: stack them or shrink the logo at that breakpoint
```

No preamble, no closing summary paragraph — the list is the report. If
nothing worth flagging survives the checklist, say so in one line instead of
padding the report with minor nitpicks.
