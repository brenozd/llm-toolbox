# storyboard-video: plano de melhorias (baseado em transcript.txt, sessão embedded-flow, 2026-11-02)

## 1. O que o transcript mostra

Limite: o transcript é um resumo de 8 itens, não o diálogo bruto. Retrabalho "N vezes" só é visível onde ele cita (itens 2→3, 6). Para métrica real, ler o session log.

### Funcionou (o usuário aprovou ou não reclamou)
- Edição direta do `spec.json` + `validate_spec`/`verify` como rede de segurança. Pegou `bad_evidence`, `callout_too_long`, `silent_unreadable`, `long_silence` antes do render.
- `evidence` file:line forçou citar `cloud-exporter.md:24` (5 min, hot-reload) em vez de inventar.
- `stills()` com 0 findings antes do delivery; "Ficou bom, faça render final".
- `direction.palette` + `palette_source: user` (design system do usuário aplicado em 1 edição).
- Gate delivery: stills → render → verify, com recibo (resolved_hash, LUFS, fps).

### Dor / retrabalho
| # | Dor | Causa raiz | Onde mora |
|---|-----|-----------|-----------|
| P1 | Frame 00:51 poluído (comando enorme) → refazer captura | Nada checa densidade de uma cena `terminal` capturada; só `lines` ≤18 | spec.py lint; SKILL "Capture" |
| P2 | CPU "0%" → 2ª rodada de captura, bug do `pgrep` | Captura de métrica em host remoto sem protocolo de medição (amostra única BusyBox). Skill diz "real output" mas não "mede com janela" | SKILL (remote target) |
| P3 | Script `/tmp/flow_stats.sh` efêmero, usuário perguntou "onde está?" | Artefato que gera a captura não é gravado junto da captura (`recipe`) | capture_* / SKILL |
| P4 | `render(profile=…)` caiu em draft 2x sem erro | Kwarg desconhecido ignorado pelo tool; `quality` default `draft` | server.py:182 |
| P5 | `narrate` ressintetizou 24 cenas após mudar tema/hash, texto idêntico | Manifest em `audio/<spec_hash>/`; cache de linha existe (tts.py:67) mas a manifest/recibo é por hash. Verificar se o cache de linha de fato falhou (hipótese a testar) | tts.py:134-165 |
| P6 | `long_silence` por encurtar narração sem reduzir `duration_s` | `duration_s` e narração são campos independentes editados à mão | spec.py/audio.py |
| P7 | 4K não existe; upscale manual por ffmpeg | Resolução presa em `ASPECTS` | spec.py:17, render.py:725 |
| P8 | Limpeza manual de ~30 pastas + 493MB root-owned | Container roda como root e escreve em `sb-view/`; sem `clean`/`gc` | Dockerfile, sem tool |
| P9 | Tema do design system exigiu ler artifact e mapear tokens à mão | Sem `brand_tokens` para fonte externa (URL/tokens.json) | brand_tokens |
| P10 | Aviso de contraste (accent 3.06:1) só informado, aceito como warning | `palette_source: user` rebaixa a warning (decisão consciente, ok) | manter |

## 2. A spec que governa (o ponto principal)

### O que a pesquisa diz
- **JSON2Video / Shotstack / Creatomate**: documento declarativo `movie → scenes[] → elements[]`, JSON Schema/OpenAPI publicado, e *"help for AI agents"* (`llms.txt`, "Rules for your agent"). Lição: publicar o schema + regras para o agente consumir, não só prosa no SKILL.
- **Remotion**: `zod` schema nos props + `calculateMetadata()` deriva `durationInFrames/fps/width/height` dos dados. Lição: **duração derivada, não digitada**.
- **Spec-first + lint + QA (dev.to, "timed spec first")**: decisões de história viram dados (`hook`, `sees`, `understands`, `opens/closes`), linta-se com script PASS/FAIL, **blind read** (outro agente descreve o still sem ler a spec; compara com `understands`), revisor separado do autor. Lição: campo `understands` por cena + blind read já é quase o que o `4b` do SKILL faz.
- **ai-video-editor command contract**: edição por **plano de operações** (`baseRevision`, `dryRun`, `operations[]` com id idempotente, `project.diff` antes de aplicar, envelope `ok/code/operationId`). Lição: o LLM não reescreve o JSON inteiro, envia patches validados.
- **OpenTimelineIO**: spine de edição (tracks/clips/markers) como interchange; útil só para export a NLE, não como formato nativo aqui.

### Onde a spec atual já acerta
`direction` (brief/arc/roles/must_avoid/pacing) + `evidence` + `validate_spec` + hash = 80% do padrão.

### Lacunas frente ao estado da arte
1. **Sem JSON Schema publicado.** O contrato só existe no SKILL.md (33 KB, lido de novo a cada sessão) e em spec.py. LLM erra campos (`evidence:"file:24,30"`).
2. **Edição = reescrever JSON/hash novo.** Mudar uma cena troca o hash e invalida narração (P5).
3. **Duração digitada à mão** (P6, e `silent_unreadable`).
4. **A spec não registra a *fonte* de cada cena** (qual captura, qual comando, qual script) → P3 e reprodutibilidade.
5. **Sem campo de intenção por cena** (`sees`/`understands`), então "poluído" (P1) não é checável.

## 3. Plano em buckets (cada um ≈ 1 PR, ordem por retorno/esforço)

**B1: guard-rails baratos (P4, P1).**
- Tools rejeitam kwargs desconhecidos (FastMCP/pydantic `extra="forbid"`) e `render` sem `quality` explícito retorna erro listando valores válidos.
- Lint `dense_capture` em cena `terminal`/`image`: >N chars por linha, >M linhas visíveis, ou comando >1 linha longa → warn com sugestão "crie um script curto".
- Done when: teste que passa `profile=` e recebe erro; teste do lint com o comando do 00:51.

**B2: spec como contrato publicado.**
- Gerar `spec.schema.json` (de dataclass/pydantic ou à mão a partir dos lints) e expor como resource MCP + tool `get_spec_schema`. SKILL passa a apontar para ele e encolhe a seção Spec.
- `validate_spec` devolve JSON Pointer do campo (`/scenes/3/evidence`) e correção sugerida; `bad_evidence` aceita a forma `file:24` e explica `file:24-30`.
- Done when: schema valida o spec.json da sessão; erro cita pointer.

**B3: duração derivada + edição por patch.**
- `duration_s: "auto"`: calculada da narração (+ respiro) após `narrate`, com `min_s` opcional. Remove P6 e `silent_unreadable` por construção.
- Tool `patch_spec(spec_hash, ops[], dry_run)` com ops `replace/add/remove/move` por id de cena (estilo JSON Patch, ids estáveis), retorna diff, lint e novo hash. Narração: cache por linha (já existe) reaproveitado, verificar P5.
- Done when: trocar tema não ressintetiza nada; remover cena atualiza `direction.scenes` junto (hoje manual, ver item 1 do transcript).

**B4: campos de intenção e proveniência na cena.**
- `scene.intent: {sees, understands}` (opcional; obrigatório se `direction.strict`), `scene.source: {capture_id|command|script_path, measured_at}`.
- `capture_*` grava o script/alias usado em `captures/<id>/recipe.json` e devolve o caminho (resolve P3).
- Blind read vira tool/etapa documentada: `stills` → subagente sem spec descreve → compara com `understands` (reaproveita lens "cold viewer").
- Done when: cena sem `intent` em modo strict falha; recipe lista o script.

**B5: protocolo de medição remota (P2) no SKILL, não em código.**
- Regra: métrica ao vivo = janela de ≥2 amostras em /proc (ou equivalente), repetir ≥3x e reportar faixa; nunca amostra única. Linha curta, ~3 linhas.

**B6: saída, 4K e limpeza (P7, P8, P9).**
- `render(quality="delivery", scale=2)` ou `deliver(..., size="4k")` marcando no recibo `upscaled: true` (honesto: Lanczos de master 1080p), ou renderizar nativo se o renderer é HTML/CSS (viewport 3840 deve nascer nítido: investigar antes de upscalar).
- Container escreve como o UID do host (`--user`), e tool `clean_work(keep=[captures,delivery])` com dry-run.
- `brand_tokens(source=url|path)` lê `tokens.json`/CSS vars e devolve palette + checagem WCAG com o fundo.

## 4. Recomendação de ordem
B1 → B2 → B3 (maior ganho: tira os erros recorrentes), depois B4. B5 é editar texto. B6 por demanda.

## 5. Riscos / não verificado
- P5 é hipótese: ler `tts.py:134-165` para confirmar se o cache por linha foi invalidado ou só a manifest.
- `extra="forbid"` pode quebrar clientes que mandam args extras; checar o suporte do FastMCP instalado.
- Transcript é resumo: contagem de retrabalho real exige o session log.

## Fontes
- JSON2Video: https://json2video.com/docs/v2/help-for-ai-agents/rules-for-your-agent
- Shotstack: https://shotstack.io/docs/guide/getting-started/core-concepts/
- Remotion schema/calculateMetadata: https://www.remotion.dev/docs/schemas , https://www.remotion.dev/docs/calculate-metadata
- Timed-spec-first QA: https://dev.to/mohd_yusufkhan_6c2088c04/how-we-structure-an-animated-horror-reel-with-claude-code-timed-spec-first-then-shots-then-qa-1lbj
- Command contract (plan de operações, baseRevision, dryRun): https://github.com/MartinDelophy/ai-video-editor/blob/main/skills/edit-timeline-studio/references/command-contract.md
- OpenTimelineIO: https://github.com/AcademySoftwareFoundation/OpenTimelineIO
