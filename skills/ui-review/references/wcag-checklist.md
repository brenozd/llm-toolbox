# WCAG 2.2 AA checklist

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
