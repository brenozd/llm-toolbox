# llm-toolbox

MCP servers packaged as OCI containers, in Python, plus reusable Claude Code skills.

## Servers

- [`servers/actual-budget`](servers/actual-budget/) — integrates with [Actual Budget](https://actualbudget.org).

## Skills

- [`skills/caveman-sweep`](skills/caveman-sweep/) — iterative find-and-fix sweep: scan, triage, fix, rescan until clean.
- [`skills/doc-audit`](skills/doc-audit/) — syncs documentation with current code implementation.
- [`skills/guided-build`](skills/guided-build/) — goal-first, checkpoint-driven build process.
- [`skills/tech-blog-post`](skills/tech-blog-post/) — writes a technical blog post in a senior-engineer voice.

These skills are written for and depend on the following plugins (install them separately):

- [caveman](https://github.com/JuliusBrussee/caveman) — ultra-compressed communication mode.
- [ponytail](https://github.com/DietrichGebert/ponytail) — lazy/minimal-solution enforcement mode.
