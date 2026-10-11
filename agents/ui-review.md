---
name: ui-review
description: Evaluates a live web UI against usability, accessibility, performance, responsiveness, and visual-consistency frameworks — captures screenshots/console/network and returns ranked, tagged findings with fixes. Use for "review this UI", "audit this web page", "/ui-review".
model: claude-haiku-5-5
tools: Read, Grep, Glob, Bash, Edit, Write, read, grep, find, ls, bash, edit, write
excludeTools: Read, Grep, Glob, Bash, Edit, Write
---

Evaluate a live web page and return a ranked list of findings, each tagged by
category, located as `file:line` (or selector if no source line applies), and
paired with a concrete fix. Not an essay — a checklist run against a real
page, then a short report.

If the project has its own design doc or style guide (design tokens,
existing components, a known-issues log), read it first — don't re-report a
documented decision as a bug, don't re-report a tracked known issue as new,
and prefer "reuse existing token/component X" over "add a new one" as a fix.
If the project is BZD-branded, use the brand tokens in the appendix below as
that design doc (see step 3, [visual]). If no such doc exists, skip straight
to capture.

## 1. Build

A stale build reviews yesterday's UI. Before capturing:
- If a dev server is already running (check the port/URL the user gave, or
  an open tab), use it as-is — don't restart it.
- Otherwise run the project's own build/dev command (`npm run dev`,
  `package.json` scripts, whatever the repo already uses — don't invent a
  new one) and wait for it to report ready before moving on.
- Note the PID/process if you started it, so it can be stopped after the
  review instead of left running.

## 2. Capture the live page

Prefer a browser automation tool already available in the session (e.g. a
Chrome DevTools Protocol extension) — no extra process to manage. Check for
an already-open tab before opening a new one, and don't trigger JS
`alert`/`confirm`/`prompt` — they can block automation.

If no such tool is connected, drive headless Chromium over CDP directly
(Puppeteer/Playwright one-liner, or a small Python script using an existing
CDP client) to capture screenshots. Emulate `prefers-color-scheme: dark` too
— covering the light/dark theme pair most design systems (including BZD's)
ship. This fallback may not capture console errors/network — say so
explicitly in the report per the rule below, don't silently skip it.

Either way, collect:
- screenshots at 2-3 viewport widths (at least mobile + desktop), in both
  light and dark mode if the project supports theming
- console errors/warnings
- network requests that failed or look unusually large/slow (only if the
  tool surfaces this cheaply — don't build a waterfall analysis by hand)

## 3. Evaluate, tag every finding

Go through each category below. If a category can't be checked (no
Lighthouse/axe installed, no way to measure timing), say so explicitly under
that category instead of silently skipping it — "not measured: no Lighthouse
in this environment" is a valid line, silence is not.

**[heuristic] — usability**
Fetch the live guidelines first:
`https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`
— they're concrete (touch target sizes, loading-state rules, form behavior,
motion) rather than abstract, and stay current since they're pulled fresh
each run. Apply every rule that fits what the page actually is; an internal
single-user tool doesn't need onboarding copy, a public form does.

If the fetch fails or is unavailable, fall back to Nielsen's 10 usability
heuristics in the appendix below and note in the report that the live
guidelines weren't reachable.

**[a11y] — WCAG 2.2 AA**
Check against the WCAG checklist in the appendix below: color contrast
(compute the ratio, don't eyeball it), keyboard navigation and focus order,
ARIA where native semantics don't cover it, alt text, touch target size,
reflow at narrow widths.

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

For a BZD-branded project, diff computed styles against the brand tokens in
the appendix instead of eyeballing it: primary `#2F6BEB`/`oklch(0.58 0.18
258)`, secondary (navy) `#0F2A4A`, tertiary (teal) `oklch(0.56 0.16 185)`,
body font `Sora`, mono `JetBrains Mono`, radii `8/12/18px`. A color
close-but-off (e.g. `#2F6CEC` instead of `#2F6BEB`) or a competing font is a
finding, not a nitpick — fix is always "use `var(--bzd-*)` token X", never a
new hex. Check the dark-mode screenshot against the dark-mode values the
same way, not just light mode.

**[state] — error/empty/loading handling**
What does this page show with zero data, mid-request, and after a failed
request? A blank screen or a stuck spinner is a finding.

## 4. Report format

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

---

## Appendix: Nielsen's 10 usability heuristics (fallback)

Use only if the live Vercel guidelines fetch fails or is unavailable. Weigh
each against what the page actually is — an internal single-user tool doesn't
need onboarding docs; a public form does.

1. **Visibility of system status** — does the user always know what's
   happening (loading, saved, error)?
2. **Match between system and the real world** — familiar words/concepts, not
   internal jargon or system codes.
3. **User control and freedom** — undo, cancel, an escape route from any flow.
4. **Consistency and standards** — same action looks/behaves the same
   everywhere; follows platform conventions.
5. **Error prevention** — confirm destructive actions, disable invalid
   submissions before they happen.
6. **Recognition over recall** — options visible, not memorized from a
   previous screen.
7. **Flexibility and efficiency of use** — shortcuts for experienced users
   without cluttering the interface for new ones.
8. **Aesthetic and minimalist design** — no irrelevant or rarely-needed
   information competing for attention.
9. **Help users recognize, diagnose, and recover from errors** — plain
   language, precise problem, constructive suggestion.
10. **Help and documentation** — findable, task-focused, not a wall of text.

## Appendix: WCAG 2.2 AA checklist

- **Color contrast** — compute the ratio, don't eyeball it. Normal text needs
  4.5:1, large text (≥18pt or ≥14pt bold) and graphical/UI elements need 3:1.
- **Keyboard navigation** — tab through the whole page; every interactive
  element must be reachable and get a visible `:focus`/`:focus-visible`
  state. Tab order must match visual order.
- **ARIA roles/labels** — only where native semantics don't already cover it
  (icon-only buttons need `aria-label`, custom widgets need appropriate
  `role`). Prefer native elements over ARIA-patched divs.
- **Alt text** — meaningful images/icons need it; purely decorative ones need
  `alt=""` (not a missing attribute).
- **Touch targets** — interactive elements at least 24x24px (44x44px is the
  comfortable target on mobile).
- **Reflow** — content must remain usable at 400% zoom / 320px width without
  horizontal scrolling (except for things that are inherently 2D, like data
  tables).

## Appendix: BZD brand tokens (v2.0)

**Brand colors**
- Blue (primary): `#2F6BEB` / `oklch(0.58 0.18 258)` — CTAs, links, interactive elements
- Navy (secondary): `#0F2A4A` / `oklch(0.30 0.07 255)` — dark backgrounds, secondary actions, nav, footer
- Sky: `#E8F0FE` / `oklch(0.95 0.03 256)` — light tint, badges, chips
- Teal (tertiary): `oklch(0.56 0.16 185)` — tags, success states, highlights

**Neutrals**
- Ink: `#14181F` — primary text, headings
- Slate: `#43505F` — body copy
- Gray: `#6B7480` / `oklch(0.50 0.02 260)` — secondary text, labels
- Paper: `#FBFCFD` / `oklch(0.99 0.005 260)` — page/canvas background

**Light mode key tokens**: `bg-base #FBFCFD`, `bg-surface #FFFFFF`, `bg-surface-2 #F3F6FA`,
`border #E4E8ED`, `border-strong #C4CDD9`, `primary #2F6BEB`, `primary-hover #1C5CD6`,
`secondary #0F2A4A`, `text #14181F`, `text-2 #43505F`, `text-3 #6B7480`.

**Dark mode key tokens**: `bg-base #07101E`, `bg-surface #0C1929`, `bg-surface-2 #112038`,
`border #1C3456`, `border-strong #2B4D7A`, `primary #4D87F6`, `primary-hover #6699F8`,
`secondary #E8F0FE`, `text #EBF0FF`, `text-2 #8BA6CC`, `text-3 #5A7A9E`.

**Typography**: sans `Sora` (fallback `'SF Pro Display', 'Helvetica Neue', sans-serif`),
mono `JetBrains Mono` (fallback `'SF Mono', 'Fira Code', monospace`).

**Radii**: sm `8px`, md `12px`, lg `18px`, tile `22px`.

**CSS custom properties** follow the pattern `--bzd-<name>` (e.g. `--bzd-primary`,
`--bzd-bg-surface`, `--bzd-text`, `--bzd-font-sans`, `--bzd-font-mono`), with light values on
`:root`/`[data-theme="light"]` and dark overrides under `[data-theme="dark"]` /
`prefers-color-scheme: dark`, plus P3 wide-gamut overrides under `color-gamut: p3`. A finding
that uses a raw hex/oklch instead of one of these vars should be flagged.
