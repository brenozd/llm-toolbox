# tech-blog-post

Writes a technical blog post in the style of a senior programmer documenting something they actually did — to remember it later and save the next person the pain. Produces raw Markdown with frontmatter ready for Astro, Hugo, or similar static site generators. Direct, opinionated, links to upstream issues/commits/docs inline.

## Trigger

`/tech-blog-post`, or phrases like "write a blog post about", "document this for my blog", "turn this into a post", "write up what I did", "help me write about", or pasting a solved problem and saying "make this a post".

## Files

- `SKILL.md` — skill instructions.
- `WRITING.md` — authoritative writing guide (tone, structure, mandatory rules). Read in full before writing. Everything in it overrides default behavior; `SKILL.md` only adds blog-specific config on top.

## What it does

1. Reads `WRITING.md` in this directory before writing anything.
2. Asks for topic, what happened (problem, solution, environment, exact errors, failed attempts, what worked).
3. Writes the post per `WRITING.md`'s mandatory structure and tone rules.
4. Outputs Markdown with frontmatter, inline references to sources.
