---
name: tech-blog-post
description: "Write a technical blog post (raw Markdown with frontmatter for Astro/Hugo) from something the user actually did, in a direct, opinionated senior-dev voice. Use for: \"write a blog post about\", \"turn this into a post\", \"write up what I did\", /tech-blog-post."
metadata:
  version: "0.1.0"
---

# Tech Blog Post Skill

## Before you start

**Read `WRITING.md` (in this skill's directory) in full before writing anything.**
That file is the authoritative writing guide. Everything in it overrides any default behavior.
The sections below are blog-specific configuration that extends WRITING.md — they do not replace it.

## What to ask the user

Before writing, collect:

1. **Topic** — what is the post about?
2. **What happened** — the problem, the solution, the environment. Specific errors, failed
   attempts, what finally worked. Ask for exact error messages, kernel versions, hardware
   models, package versions — whatever is relevant.
3. **References** — any links the user has: GitHub issues, upstream commits, kernel docs,
   vendor datasheets, forum threads, man pages. These go inline in the post, not in a list.
4. **Language** — EN only, PT only, or both (EN + PT pair)?

If the user already provided all of the above in their message, go straight to writing.
Don't ask for information you already have.

## Audience

Programmers and sysadmins who know the basics. Don't explain what Docker is, what PCIe is,
what a terminal is. Skip all on-ramp prose.

## Frontmatter

This blog uses AstroPaper v6. Frontmatter must match the schema exactly:

```yaml
---
title: "<descriptive, problem/outcome-oriented, 50–70 characters>"
author: Breno Zanato Detomini
pubDatetime: <YYYY-MM-DDT00:00:00Z>
slug: <slug-matching-filename-without-extension>
featured: false
draft: false
lang: en          # "en" or "pt"
tags:
  - tag1
description: "<one factual sentence — what the post covers, no marketing>"
---
```

Optional fields: `modDatetime`, `ogImage`, `canonicalURL`, `hideEditPost`, `timezone`.

Set `modDatetime` (same `YYYY-MM-DDT00:00:00Z` format as `pubDatetime`) whenever editing an
already-published post substantively — not for typo fixes, but for anything that changes
structure or adds real content (new section, restructured headings, added findings).

## Bilingual posts (EN + PT pair)

If the user wants both languages:

- English file: `posts/<slug>.md` with `lang: en`, frontmatter `slug: <slug>`
- Portuguese file: `posts/<slug>-pt.md` with `lang: pt`, frontmatter `slug: <slug>-pt`

**The PT frontmatter `slug` must carry the `-pt` suffix, matching the filename — never the
bare EN slug.** Giving it the same slug as the EN post causes the two to collide upstream and
the PT content gets served at the EN URL. Always double check the PT file's `slug` ends in
`-pt` before finishing.

Both files must maintain 1:1 section parity — same sections, same order, same headings
structure. If a section is added to EN, add it to PT and vice versa.

PT UI strings (if any new UI copy is introduced) go in `src/i18n/lang/pt.ts`.

## Mandatory structure (from WRITING.md)

In order:

1. **Frontmatter** (as above)
2. **TL;DR** — `**TL;DR:** <why>. <how>.` — immediately after frontmatter, before any heading.
   Written for a reader who already knows the domain. Cover the full causal chain for the
   *why* and all significant steps for the *how*. Length follows content.
3. **Abstract** — italic, 2–4 sentences. Summarises the THESIS, not the topics. Must be
   defensible as a central argument even without the post.
4. **Hook** — first 2 paragraphs after the abstract. Use one of six techniques from
   WRITING.md. NEVER open with "In this post, I will..." or "[Tool X] has [feature Y] that..."
5. **Context anchor** — who this is for, what the reader should already know, why this
   post exists.
6. **Table of Contents** — required if post is over 1500 words. This blog auto-populates the
   ToC at build time via `remark-toc`, but its heading-match regex is English-only
   (`table of contents` / `toc`). For an EN post, a bare `## Table of Contents` heading is
   enough — the list fills in automatically. For a PT post, `## Índice` / `## Sumário` does
   **not** auto-populate: write the linked list by hand, matching the H2/H3 structure below it,
   and keep it in sync if headings change later.
7. **Body** — H2/H3 headings describe *what happens*, not just topic names. Ordered:
   problem → analysis → solution → edge cases → alternatives.
   - **H3 subheadings**: any H2 section running past ~400 words with a natural shift in
     sub-thesis (e.g. "what we found" vs "what we tried", or splitting a fix into its parts)
     gets broken into H3s. Don't force H3s into short, single-idea sections.
   - **Direct-answer block per major H2**: immediately after each major H2 (skip trivial ones
     like "References" or a short context-setting section), add a 134–167 word blockquote
     (`> **Direct answer:** ...` / `> **Resposta direta:** ...` in PT) stating the section's
     core finding before the narrative detail — written so a reader who reads only that block
     gets the real answer. The narrative that follows supplies the reasoning and evidence; the
     block supplies the conclusion. Don't restate it verbatim in the prose below. This is for
     GEO citability and skimmers, not a summary-of-the-summary — keep it specific and load-
     bearing, not generic.
   - **Question-form headings**: convert a narrative H2/H3 to question form only where it reads
     naturally (roughly 30–50% of narrative headings, not all — forcing every heading into a
     question reads as SEO spam). Imperative/step headings ("Set the password", "Enable X")
     stay as-is; only narrative statement headings are candidates.
8. **Synthesis/closing section** — use a descriptive H2 (not "## Conclusion"). Synthesis +
   practical implication + next steps. Never summarise what was just said.
9. **References** — always the last section. Bulleted list of Markdown links, each followed
   by an em-dash and one phrase explaining *why* it's there — not what it is.

## Output

Raw Markdown only. No preamble, no explanation, no "here's your post". Just the Markdown,
starting with the frontmatter block.

If producing a bilingual pair, output both files clearly separated.
