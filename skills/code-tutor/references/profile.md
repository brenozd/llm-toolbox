# Project profile

The tutor must know what is being built, not only which language. "Rust" is too generic; "an
HTTP/1.1 server in Rust on tokio" has its own mechanics, pitfalls and learning path. The profile
captures that once and every review reuses it.

Stored in `.tutor/profile.md` (self-ignoring directory, never committed). The user may edit it by hand.

## 1. Detect

Read, in this order, only what exists:

1. `AGENTS.md`, `CLAUDE.md` (project conventions, forbidden things, commands)
2. `README*` (what the project is for)
3. Manifest and lockfile: `Cargo.toml`/`Cargo.lock`, `package.json`, `pyproject.toml`, `go.mod`, `CMakeLists.txt`, `build.zig.zon`, `pom.xml`, `build.gradle`, ...
4. Tree to depth 2, entry points (`main.*`, `src/lib.*`), the test layout
5. CI config and linter config (they define the project's own quality bar)

Infer: language + edition/version, **domain** (what kind of thing: http-server, cli, parser,
game loop, embedded driver, REST API client, compiler...), key dependencies and their versions,
conventions (error handling crate, formatter, test style), and the user's apparent level (from
the code itself, not from asking).

Ambiguous domain (two plausible readings)? Ask. Clear? Do not ask extra questions.

## 2. Confirm (one line, wait for the answer)

> Entendi: servidor HTTP/1.1 em Rust (tokio, sem framework), nível: intermediário em async. Certo?

The user's correction beats the inference. Do not research before this is confirmed.

## 3. Research

Goal: a short, sourced understanding of the domain, and of the dependencies the user chose.

Collect, using WebSearch/WebFetch:

- **How it works**: the spec, standard or canonical reference for the domain (RFCs for protocols, language reference for parsers, datasheet for hardware) and the lifecycle/flow (e.g. connection accept → parse → route → respond → close).
- **Good practices** for the domain and for the language *in that domain* (e.g. async Rust: do not block the runtime; HTTP: timeouts, limits, graceful shutdown).
- **Pitfalls and security**: known failure modes and the relevant OWASP/CWE/CERT entries.
- **Key dependencies**: official docs for the 2-4 deps that matter, at the version in the lockfile.
- **Language guidelines**: the language's official style/API guidelines.

Source rules:

- Official first: spec/RFC, language docs, dependency docs, standards bodies. Blogs and forums only as complement, and say so.
- Cite a URL only if it was opened in this session. Never invent or "remember" URLs.
- Mark each point `(spec)`, `(doc oficial)` or `(comunidade)`.
- No web tool available: build the checklist from general knowledge and mark every item `(não verificado)`.
- Prefer stable anchors (RFC section numbers, doc page titles) over deep links that rot.

## 4. Save

Write `.tutor/profile.md` with the tool `tutor_save_profile` (or directly under `.tutor/` if the
tool is absent). Keep it short: it is injected into the prompt every turn (truncated at ~8000 characters).

Template:

```markdown
# Perfil
domínio: http-server (HTTP/1.1)
linguagem: rust (edition 2021)
deps-chave: tokio 1.x, httparse 1.x
convenções: <resumo do AGENTS.md, formatter, crate de erro, estilo de teste>
nível: intermediário (async: iniciante)
atualizado: <data>

# Como funciona
- <3-6 linhas: fluxo do domínio, com fonte (spec) / (doc oficial)>

# Checklist de domínio
- [ ] <item> — por quê; fonte (spec|doc oficial|comunidade) <url aberta>
(máx. 10; cada item é algo que um review pode verificar no código)

# Roteiro
1. <passo, em ordem de aprendizado do domínio>
(máx. 8; é a fonte do "próximo passo")

# Conceitos vistos
- <conceito>: ok | travou Nx | revisitar
```

## 5. Refresh

- Manifest or AGENTS.md changed (new dependency, new module): research only the delta, edit the affected parts, keep "Conceitos vistos".
- `refresh` mode: redo steps 2-4 fully, preserving "Conceitos vistos".
- Profile older than the user's confirmed scope (e.g. the project pivoted): ask before rewriting.

## Example (illustrative, not researched content)

Domain `http-server` in Rust: checklist items usually revolve around request framing and body
delimiting, header/size limits, read/write timeouts, keep-alive handling, backpressure, graceful
shutdown, routing and error-to-status mapping, and not blocking the async runtime. The real
list must come from the research step for the actual project, with sources.
