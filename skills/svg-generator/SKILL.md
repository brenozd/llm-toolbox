---
name: svg-generator
description: |
  Generate or edit an SVG by hand-writing SVG/XML markup directly (no DOM library,
  no per-element wrapper scripts), using a write -> render -> self-evaluate -> revise
  loop until the result is aligned, symmetric where expected, matches the user's
  request, and respects SVG spec rules — or a fixed iteration cap is hit.
  Use when: "create an svg", "generate an icon/logo as svg", "edit this svg",
  "make a vector [shape/icon/illustration]", "/svg-generator".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - WebSearch
---

# svg-generator

Write real SVG markup directly. SVG is XML — don't reach for a DOM library or
per-element CLI wrapper to add a `<rect>`; just write/edit the tag.

## 0. Understand the ask

Before searching or writing anything, pin down:

- **Subject** — what the image literally depicts (a cat, a gear logo, an abstract
  blob pattern...).
- **Style/constraints** — flat/line-art/isometric/gradient, color palette, size/use
  (favicon vs. hero illustration), symmetry expectations, any explicit rule the
  user stated.
- **Search tokens** — 2-4 short distinct phrases derived from subject + style
  (e.g. subject alone, subject + style, subject + "logo"/"icon"/"silhouette").
  Skip tokens for purely abstract/geometric requests with no real-world subject.

State this as a one-line context brief, e.g.:
`brief: flat-style cat icon, round/friendly, 2-color, tokens: "cat icon flat", "cat silhouette", "cat face logo"`.

This brief drives both the search in step 0.1 and the eval criteria in step 3.

## 0.1 Reference (optional, skip for trivial/abstract shapes or no tokens)

Run one web image search per token from the brief (2-4 searches). Pull 1-3
images per query. Use them to calibrate shape, proportion, and palette — never
trace/copy a result 1:1 (license risk); the output must be your own geometry.

## 1. Write

- Author the file directly with `write`/`edit`, as plain SVG/XML.
- If the request is an **app/product icon**, ask (or assume, stated explicitly) whether it
  needs: a transparent-background variant (no `<rect>` backdrop — for composing into
  launchers/favicons that supply their own shape), light- and dark-mode variants (same
  foreground artwork, swap background and/or stroke color so it stays legible on both),
  and confirm the subject is centered in the viewBox with even margins — most icon
  surfaces (favicon, app launcher, macOS dock) crop/mask to a circle or rounded square,
  so off-center art gets clipped. Ship these as separate files (`icon.svg`,
  `icon-transparent.svg`, `icon-dark.svg`...), not one file with hidden layers.
- Core structure: `viewBox="0 0 W H"`, shapes (`rect`, `circle`, `ellipse`,
  `path`, `line`, `polygon`, `text`), `<g>` for grouping/transforms, `<defs>` +
  `<linearGradient>`/`<radialGradient>` for fills, `transform="translate/rotate/scale"`
  for positioning.
- On revisions (step 4), edit the existing markup incrementally — don't regenerate
  from scratch unless the structure is fundamentally wrong.
- Freehand bezier curves for recognizable real-world subjects (anatomy, animals, objects)
  are hard to get right and easy to burn iterations on. If 1-2 passes of hand-drawn
  geometry aren't reading clearly, stop guessing coordinates — pull a proven path from
  an open-license icon set (Iconify: `curl "https://api.iconify.design/<prefix>/<name>.svg"`,
  see the `icon-search` skill) as the base shape, then recolor/recompose/add your own
  accents around it. Reusing a tested glyph's path data is not the same as tracing a
  photo — check the set's license (most Iconify sets are MIT/Apache/CC0).
- Iconify has multiple icon sets per keyword (`tabler:`, `lucide:`, `ph:`, `bi:`...) with
  wildly different quality for the same subject — render 2-3 candidates side by side
  (one small comparison SVG, not separate renders) before committing to one; don't
  anchor on the first result returned.
- Don't bolt extra meaning onto a subject with disconnected decorations (e.g. floating
  bars "for multi-speaker" next to an unrelated ear shape) — if an extra concept doesn't
  integrate into the main shape cleanly, it reads as clutter/debris, not intent. Cutting
  it is often the fix the evaluator asks for.

## 2. Render

Rasterize to PNG to actually see it before judging it, via the `screenshot` skill’s
web-capture path — Chromium renders bare `.svg` files directly, no HTML wrapper needed:

```bash
python3 <path-to-screenshot-skill>/scripts/shot.py --web "file://$(realpath file.svg)" --viewport --output /tmp/svg-preview.png
```

Fallback if Chromium isn't on PATH: `rsvg-convert -w 512 -h 512 file.svg -o /tmp/svg-preview.png`
(or `resvg`/`inkscape` equivalents).

## 3. Evaluate

Don't self-grade — the author (you, having just written the markup) already knows what the
shape is supposed to be, which makes self-scoring systematically too generous. Delegate the
score to the `devils-advocate` subagent, which only sees the render and the brief, not the
process that produced it:

```
subagent({
  agent: "devils-advocate",
  task: "Read the image at <preview-path>. You have not seen how it was made — just this
         brief: '<the step 0 one-line brief>'. Score 0-10, strict, as a first-time viewer:
         - Recognizability: does the subject read as itself within ~1 second, unprompted?
         - Element count sanity: do repeated elements (waves, petals, points...) count cleanly
           by eye, matching what the brief implies?
         - Alignment/composition: centered, balanced use of the canvas, no dead space?
         - Symmetry: only score if the brief implies it.
         - Fit to brief: subject/style/colors match?
         - Spec/polish: clean linework, no glitches?
         One-line justification per score, then overall verdict: ship it or name the single
         biggest fix.",
  async: true
})
```

Use `async: true` (MCP/image-reading tools need it to load) and wait on the result before
continuing. If recognizability scores ≤4, that's an automatic revise regardless of the other
scores — don't let strong "fit"/"spec" scores mask an unrecognizable subject. When in doubt,
have it compare against a step 0.1 reference image too.

State the subagent's scores in one short line per iteration, e.g.:
`iter 2: recognizability 3, align 8, fit 6, spec 10 -> ear unrecognizable, redrawing helix/lobe`

## 4. Stop condition

- Overall score ≥ 8/10 average → done, deliver the file.
- Otherwise fix the lowest-scoring aspect and loop back to step 1 (edit, don't rewrite).
- Hard cap: 3 iterations. If still below threshold after 3, deliver the best
  version seen and say so plainly with the final scores — don't loop silently.

## Output

End with the file path and the final score line. No separate report file.
