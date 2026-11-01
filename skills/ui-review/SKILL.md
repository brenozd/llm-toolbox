---
name: ui-review
description: "Multi-agent review of a web UI (UX, visual, accessibility, mobile, desktop, frontend code) consolidated into a prioritized P0-P3 fix plan. Use for: \"ui review\", \"audit this interface\", \"revise esta UI\", /ui-review."
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
metadata:
  version: "0.1.0"
---

# ui-review

Delegate to 7 parallel subagents, each auditing the app from one lens without
seeing the others' conclusions. Then consolidate into one prioritized report.

## Execution

1. Identify the app's URL/entry point and main flows before spawning agents.
2. Launch 7 independent subagents in parallel (see prompts below). Each must
   inspect the running app/implementation directly (browser + code), not assume
   the other agents' findings.
3. Consolidate: dedupe, merge related findings, flag cross-agent consensus,
   drop anything without evidence in the actual implementation.

## Agent prompts

### Agent 1 — User Journey / UX
Walk every main flow end to end as a real user. Check: clear screen goals,
obvious next actions, unnecessary steps, ambiguous decisions, dead ends, CTA
clarity, action hierarchy, loading/success/error/empty states, feedback after
actions, undo/correct affordances, hidden/hard-to-find info, nav consistency,
new vs. returning user flows.

### Agent 2 — Visual UI / Design System
Check alignment, spacing, padding, margin, grid, sizing/hierarchy, typography,
line-height, iconography, component consistency, borders/radius, shadows,
colors, hover/focus/active/disabled states, visual density, adherence to the
existing design system. Only flag issues tied to usability, consistency,
hierarchy, or the design system — not personal taste.

### Agent 3 — Accessibility / Contrast
Check text/background and interactive-element contrast, min text size, visible
focus, keyboard nav, form labels/errors, semantic hierarchy, landmarks,
button-vs-link usage, icon-only controls, tap target size, color-only-conveyed
info. Cite the relevant WCAG criterion and exact element for each finding.

### Agent 4 — Responsive / Mobile
Test at ~320/375/390/430px. Check horizontal overflow, clipped content,
non-collapsing grids, tables, cards, forms, menus, nav, modals, dropdowns,
buttons, touch target size/spacing, sticky/fixed elements, virtual keyboard,
portrait orientation. Evaluate whether interaction was actually adapted for
touch, not just shrunk.

### Agent 5 — Desktop / Large Screens
Test at 1024/1280/1440/1920px. Check max content width, space usage, grids,
section alignment, density, whitespace, sidebar/nav, tables, forms,
dashboards, sticky/fixed elements. Flag layouts that get excessively wide,
empty, or unbalanced.

### Agent 6 — Implementation / Frontend
Review semantic HTML, component structure, CSS/classes/framework usage,
breakpoints/media queries, duplicated components, conflicting styles,
needless hardcoded values, cross-breakpoint risk, JS-driven UI state,
reusability, maintainability, accessibility in the markup. Only flag things
causing bugs, inconsistency, maintenance pain, or incorrect behavior — not
style preference.

### Agent 7 — Visual QA
Compare screens/states side by side for misalignment, spacing diffs,
inconsistent component dimensions, displaced elements, typography/color/icon
inconsistency, layout shifts, uneven visual density. Treat the UI as one
system, not isolated screens.

## Finding format

Each finding: ID, category, screen/component, description, evidence, user
impact, severity, affected breakpoint/device, fix recommendation.

Severity:
- P0 — blocks the flow / feature unusable
- P1 — serious UX, accessibility, or responsiveness problem
- P2 — relevant usability or consistency problem
- P3 — minor polish

## Consolidation rules

- Dedupe; merge related findings but keep distinct evidence per agent.
- Flag cross-agent consensus explicitly.
- Prefer issues that hit UX + accessibility + responsiveness simultaneously.
- No finding without evidence in the actual implementation.
- No changes proposed for aesthetic preference alone.
- Desktop is not the reference for mobile; mobile is not desktop shrunk.
- Existing design system is the source of truth; preserve what's already correct.
- When uncertain, mark "needs validation" instead of asserting.

## Final report

1. **Executive Summary**
2. **User Journey** — table: Flow | Step | Problem | Impact | Severity
3. **UI Audit** — table: ID | Screen/Component | Problem | Evidence | Impact | Severity | Recommendation
4. **Responsive Audit** — split Mobile / Tablet / Desktop / Large Desktop
5. **Accessibility Audit**
6. **Implementation Audit**
7. **Cross-Agent Findings** — issues found by 2+ agents
8. **Prioritized Fix Plan** — ordered P0 → P3, with rationale and expected outcome per item
9. **Recommended Changes** — for each: exact element, current behavior, expected
   behavior, breakpoint, and value/component/rule to use. No vague asks like
   "improve UX" or "increase contrast" — always concrete and implementable
   without reinterpretation.
