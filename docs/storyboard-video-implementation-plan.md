# storyboard-video: plano de implementação (fases 0–5) com verificação adversarial

> **Nota (2026-10-31):** o motor de voz deixou de ser o Kokoro e passou a ser o Pocket TTS (Kyutai, binário Rust, sem Python). As menções a Kokoro abaixo descrevem o estado quando o plano foi escrito; veja `servers/storyboard-video/README.md` para o estado atual.

Companheiro de `storyboard-video-pro-pipeline.md` (pesquisa e desenho). Este documento é o plano executável.
Data: 2026-10-30. Marcação: **[C]** confirmado no código · **[?]** hipótese a verificar num spike antes de codar.

## Decisões do usuário (fixas)
1. `role` ganha `implication` e `result` → `{hook, problem, implication, reveal, value, proof, result, cta}`.
2. Loudness padrão **−14 LUFS** (web). Configurável por spec (`audio.target_lufs`), nunca constante global escondida.
3. **Sem pacote CC0 no repo.** SFX vêm de (a) `music-search` estendida com `--kind sfx` e (b) síntese procedural por ffmpeg (zero licença). Ver Fase 4.
4. Animatic **sim** (uma rodada de TTS extra; o cache por linha já existe).
5. Planejar todas as fases, com verificação adversarial por fase.

## Fatos do código que moldam o plano [C]
- `spec.py:31` `DIRECTION_ENUMS["role"]` é validado só como tipo, por cena, em `direction.scenes` (`spec.py:393`).
- `spec.timeline()` (`spec.py:132`): duração da cena = `max(duration_s, áudio + 0,4 s + transição)`. A voz é o relógio, mas `duration_s` é palpite.
- `render.narration_cues/narration_track` (`render.py:~377`): **um WAV por cena**, posto no início da cena (nunca antes do fim do anterior). Não há timing por palavra.
- `tts.narrate` grava `manifest.json` por cena. Kokoro (`eng.create`) devolve só `samples, sr`: sem timings.
- WER hoje roda **fora** do container, pela MCP `faster-whisper` (SKILL.md passo 6). Dentro do servidor não há whisper.
- `audio.py`: `TARGET_I = -16.0` constante; `TARGET_TP = -2.0`; `TP_LIMIT = -1.5`; `I_TOL = 1.5`. Testes que fixam −16: `test_audio.py:72,95`, `test_audio_mux.py:162,186`; SKILL.md linha 67 cita −16.
- `resolved_hash` = spec_hash + digest do áudio + `RENDER_VERSION` + `model_id`. **Não inclui** constantes de mix: mudar o alvo de loudness sem mexer em nada não invalida render cacheado.
- `music-search` já nega Freesound (ToS) e exige licença; Openverse, Internet Archive (ccMixter removed); sidecar `<id>.json` com `license_evidence` e `sha256`; erros são resultados.
- `test_skill_docs.py` parseia todo bloco ```json do SKILL.md e roda `normalize + lint` no bloco `## Spec`: **qualquer exemplo novo no SKILL.md é teste em CI**.

## Princípios de execução
- Uma fase = um PR = um vídeo de referência antes/depois. Nenhuma fase depende de uma posterior para ficar correta.
- Lint novo nasce `warn`; vira `error` só com dados de ≥3 vídeos de referência (limites 5 s / 8 palavras vêm de guias de marketing, não de estudo).
- Retrocompatibilidade: spec antigo (sem `brief`, `beat`, `cues`) renderiza idêntico byte a byte nos frames (comparar `digest` de stills) e só ganha warns.
- Nada de afirmar o que não foi capturado (regra de honestidade da skill) prevalece sobre qualquer regra de narrativa.

## Vídeo de referência (pré-requisito de todas as fases)
**Repo de referência: `../mint`** (rastreador de leaks via `LD_PRELOAD`; C/CMake, README curto, tem `mint_loader` para cena de terminal; commit `4525050`). Produzir 1 spec "antes" (estado atual) e arquivar em `docs/reference/before/` : `spec.json`, MP4 (16:9), `verify.json`, `stills` em 5 tempos, medição de loudness. Todo PR de fase anexa o "depois" e o diff. Sem isso, "ficou melhor" é opinião.
Critério de pronto de qualquer fase: suíte `tests/` verde **no container** (`docker run … pytest -q`), `storyboard-e2e.sh` verde, `verify` ok no vídeo de referência.

---

# Fase 0 — SKILL.md: processo profissional (só texto)

**Objetivo:** o agente passa a seguir brief → arco → hook → script AV → revisão adversarial → rodadas, sem tocar no servidor.

**Mudanças em `skills/storyboard-video/SKILL.md`:**
1. Passo 3 (entrevista) vira **Brief**: 5 perguntas de conteúdo (quem assiste/em que situação; dor em uma frase nas palavras dele; ação desejada = 1 CTA; mensagem única; onde toca: hero/ad/deck/booth/walkthrough → define duração e se precisa funcionar mudo) + 3 de config (aspecto/idioma/voz, música ou não, paleta/tom). Saída: `direction.brief = {audience, pain, promise, cta, placement}`.
   - A linguagem do cliente é minerada de README, issues, CHANGELOG e mensagens de commit via `scan_repo`; citar a fonte (`evidence`).
2. Novo passo **Arco + logline**: escolher gabarito pelo placement (tabela do doc de pesquisa §3.3), propor **2 arcos de 1 linha** + logline; usuário escolhe. Beats = o enum de `role` completo. Orçamento de tempo por beat é ponto de partida, não regra.
3. Novo passo **Hooks**: 5–10 candidatos (arquétipos: curiosity gap, claim falsificável, prova específica, pattern interrupt, stakes), 2 finalistas com o 1º frame descrito, usuário escolhe. Promessa do hook tem de ter cena `proof`/`value` correspondente.
4. **Script AV em duas colunas** (áudio exato | visual) com tempo acumulado a 2,5 palavras/s e marcadores `[beat]`; substitui a tabela de cenas. Números e textos de tela exatamente como aparecerão.
5. Passo 4b vira **revisão de 3 lentes** (espectador frio, cético, editor) com notas por cena/timecode, consolidadas em uma lista must-change × preferência, máx. 2 ciclos. Cada lente roda em subagente read-only de contexto limpo (regra de delegação do AGENTS.md: o prompt leva só o AV script e o que a lente pode ver).
6. Declarar **rodadas** com escopo: cada gate diz a pergunta da rodada e o que *não* será julgado.
7. Ordem do som: música é escolhida **depois** da voz travada (`music-search` passa para depois do lock, com a cadência da leitura).
8. Corrigir texto de loudness: linha 67 e descrição para −14 (aplicado de fato na Fase 4; até lá, **não** mudar o número para não mentir). Ver ordenação em "Riscos de integração".

**Arquivos:** `SKILL.md` apenas (+ `README.md` do servidor se citar o fluxo).
**Testes:** `test_skill_docs.py` já cobre o bloco ```json; novo exemplo de `direction.brief` precisa passar `normalize+lint` sem erro. Adicionar assertiva: o SKILL.md menciona todos os 8 roles do enum (evita drift doc↔código).

**Verificação adversarial:**
| Ataque | Como se detecta | Mitigação |
|---|---|---|
| O agente ignora o gate e despeja o roteiro todo | rodar a skill no repo de referência com um prompt vago ("faça um vídeo disso") e checar que ela **para** nos gates 1/2 | texto imperativo curto por gate + "não avance sem resposta" |
| Brief com resposta inventada ("público: desenvolvedores") | pedir o brief num repo sem README; a skill tem de perguntar, não preencher | regra: campo sem fonte → pergunta; proibir default |
| 4 gates = fricção em vídeo de 45 s | contar mensagens ao usuário na sessão de referência | juntar logline+arcos+hooks+script em **uma** mensagem (3 gates reais: arco/hook, script, animatic) |
| Template de arco gera vídeos iguais | gerar 2 vídeos de repos diferentes e comparar AV scripts | o que diferencia é `pain` na língua do cliente; lente "espectador frio" falha "genérico" |
| Doc pede o que o código não suporta (cues, animatic) | revisão cruzada: cada ferramenta/campo citado existe no servidor | marcar passos "(Fase N)" e só ativar quando a fase mergear; até lá instrução degrada para o fluxo atual |
| Exemplo JSON novo quebra CI | `test_skill_docs.py` | rodar antes do PR |

**Pronto quando:** sessão de referência produz brief+arco+hooks+AV script+revisão com ≤3 interrupções ao usuário, e nenhum campo do brief sem fonte.
**Rollback:** `git revert` do SKILL.md.

---

# Fase 1 — enum de roles + lints de narrativa e densidade (`warn`)

**Mudanças:**
1. `spec.py:31`: `role` = `{hook, problem, implication, reveal, value, proof, result, cta}`. Mensagem `bad_direction` já lista o enum via `sorted(...)`: automático.
2. `direction.brief` e `direction.arc` aceitos e validados (objeto; chaves string; `arc` ∈ `{"ad","hero","walkthrough","booth-loop"}`). Desconhecido → `warn` (não quebra spec antigo); tipo errado → `error bad_direction`.
3. `scene.beat`: alias de `role` no plano; não duplicar. **Decisão:** manter só `direction.scenes[id].role`. Sem campo novo em `scenes[]` nesta fase.
4. Lints (todos `warn`, código novo, `fix` acionável):
   - `arc_missing_beat`: sem `hook` ou sem `cta` (ou sem `problem` quando `purpose` é `sales-video`/`feature-demo`).
   - `hook_not_first`: o `hook` não é a primeira cena.
   - `hook_brand_first`: 1º frame/1ª frase abre com saudação ("olá", "hello", "bem-vindo"), nome do produto isolado ou logo.
   - `hold_too_long`: cena sem narração e sem `reveal` > 5 s (para `terminal`: já existe `MIN_HOLD_S`, não conflitar).
   - `callout_too_long`: `caption`/`items[i]` > 8 palavras (separado do `WORDY=18` existente que é "parágrafo").
   - `monotone_pace`: 3 cenas seguidas com mesmo `type` e duração ±15%.
   - `silent_unreadable`: texto na tela com tempo de leitura insuficiente (palavras / duração > 3 pal/s).
   - `no_before_after`: placement `sales-video`/`feature-demo` sem cena com `reveal`/`value` que tenha duas versões (heurística fraca: marcar só como `info`, não `warn`, até haver sinal melhor).
   - `hook_promise_unkept`: hook sem nenhuma cena `proof`/`value` posterior.
5. Calibração: um script `scripts/lint-corpus.py` roda `lint` em todos os specs de `docs/reference/` e imprime contagem por código (insumo para promover warn→error).

**Arquivos:** `spec.py`, `tests/test_spec.py`, `tests/test_skill_docs.py`, fixtures em `tests/`.
**Testes (um por lint, positivo e negativo) + regressão:**
- spec antigo (sem direction) → **zero** findings novos (guarda de retrocompatibilidade).
- `role: "implication"` e `"result"` aceitos; `"foo"` rejeitado com a lista nova.
- `hook_brand_first` em pt-BR e en; falso positivo: "Hello world" como *texto de código* num `terminal` não dispara (só narration/title/caption).

**Verificação adversarial:**
| Ataque | Detecção | Mitigação |
|---|---|---|
| Lint vira teatro: agente "conserta" mudando o texto só para silenciar o warn | amostrar 5 vídeos; checar se o texto piorou | revisor "editor" julga qualidade, lint só aponta; nunca bloquear em warn |
| Falso positivo em spec bom do corpus | rodar `lint-corpus` nos specs existentes (incl. `storyboard-e2e.sh`) | heurísticas conservadoras; precisão > recall |
| Hook com nome do produto é legítimo ("Mint: ...") | caso de teste | `hook_brand_first` só dispara se o nome é a **única** coisa nos 3 primeiros s ou há saudação |
| i18n: regex em pt-BR e en apenas | testar `lang` | lista de saudações por `lang`; idioma sem lista → pula o lint |
| Aumento de latência de `validate_spec` | cronometrar | tudo O(n cenas) |
| Quebra o `test_skill_docs` por exemplo sem `hook` | rodar | o exemplo do SKILL.md passa a incluir hook+cta |

**Pronto quando:** suíte verde; lint-corpus sem warn novo em specs existentes que o time considera bons (ou warns revisados e justificados); roles novos documentados.
**Rollback:** reverter PR; specs não mudam de formato.

---

# Fase 2 — animatic (scratch VO + rough cut barato)

**Objetivo:** ouvir o ritmo antes de capturar. Rodada 1 julga só estrutura.

**Desenho:**
- Nova flag em `narrate`: `scratch=true`. Mesmo Kokoro, mesmo cache; grava `manifest.json` com `"scratch": true` e **não** altera o `resolved_hash` final (o hash do animatic usa `stage="animatic"`; o spec final tem outro). Assim um animatic nunca é confundido com entrega.
- Nova ferramenta `animatic(spec_hash)`: usa o AV script como spec "cartão": cada cena vira `title`/`bullets` com a coluna de visual como placeholder legível ("[captura: terminal rodando X, 6 s]") + o áudio por cena, tela 360p, 15 fps, vídeo com **marca d'água "ANIMATIC"** e sem música. Retorna MP4 + `pace_map`: por cena `dur_s`, `words`, `wps`, pausa inicial/final, tipo.
  - Reusa `render` com um perfil `quality="animatic"` (resolução e fps menores, sem captura real). Não criar pipeline paralelo.
- `shot_list(spec_hash)`: gera, a partir do AV script aprovado, a lista de capturas necessárias cena a cena **com o tempo que a voz deixou** (entrada para `capture_*`). A captura passa a gravar o necessário, não "o que couber".
- SKILL.md ativa o passo 9–10: a captura só roda depois do gate "rough cut".

**Arquivos:** `tts.py` (flag e manifest), `server.py` (2 ferramentas), `render.py` (perfil de qualidade), `spec.py` (`stage`), `tests/test_tts.py`, `test_render.py`, `test_render_e2e.py`, SKILL.md.

**Verificação adversarial:**
| Ataque | Detecção | Mitigação |
|---|---|---|
| TTS regular demais engana o ritmo (humano real será mais lento/variável) | comparar duração TTS × leitura humana de 2–3 cenas | usar o animatic só para **estrutura**; sempre recalcular com a voz final; avisar no retorno `pace_map.caveat` |
| Cache do animatic polui o do final (mesma chave de texto+voz) | teste: narrar scratch e depois final → não há WAV obsoleto reutilizado errado | chave de cache já inclui texto/voz/velocidade; scratch usa a mesma e **isso é desejável** (economiza TTS); o que muda é o `manifest.scratch` |
| Animatic aprovado ≠ vídeo final (placeholders nunca refletem a captura real) | diff de durações animatic × final na referência | `shot_list` fixa a duração por cena; `timeline()` continua derivando da voz |
| Usuário vê o animatic como vídeo final | revisão manual | marca d'água, 360p, nome de arquivo `*_ANIMATIC.mp4`, fora de `out/<resolved_hash>/` |
| Custo: 2 passes de TTS | medir tempo na referência | cache por linha: só linhas alteradas pagam |
| Ordem do pipeline: stills antigos ainda exigem captura | e2e do fluxo completo | animatic não exige captura: render de cartão puro |

**Pronto quando:** na referência, animatic gerado em < ~20% do tempo do render final; `pace_map` correto (testado com WAVs sintéticos de duração conhecida); fluxo termina em vídeo final sem recapturar.
**Rollback:** ferramentas novas são aditivas; flag `scratch` default `false`.

---

# Fase 3 — cues por palavra (sincronia) — núcleo do salto de qualidade

**Spike obrigatório antes de codar [?] (1 dia, saída = decisão escrita):**
Kokoro-onnx não devolve timings (**[C]** `eng.create` → `samples, sr`). Opções, em ordem de preferência a avaliar:
- **A.** `faster-whisper` com `word_timestamps` — hoje só existe na MCP do host. Verificar se `transcribe` expõe palavras; senão, adicionar `faster-whisper` ao container (custo de imagem) ou chamar a MCP no passo `narrate` (acoplamento).
- **B.** Alinhamento próprio sem whisper: dividir a frase em palavras, ponderar por nº de sílabas/caracteres, ancorar com `silencedetect` do WAV (pausas reais) e normalizar na duração medida. Erro esperado ~50–120 ms; mede-se contra A no corpus.
- **C.** Timings de saída do modelo (duração de fonemas) se kokoro-onnx expuser (improvável).
Critério de decisão: erro mediano ≤ 80 ms e p95 ≤ 150 ms contra A em 20 frases pt-BR e 20 en. Se B passa, escolhe B (sem dependência nova); senão A.

**Desenho:**
- `narrate` grava no manifesto, por cena: `words: [{w, start_s, end_s}]` + `align: "whisper"|"estimated"`.
- Novo campo opcional `scene.cues: [{"on": "trecho da narração", "do": "reveal|count|emphasis|cut", "target": "<id do elemento>", "lead_ms": 120}]`. `on` casa **trecho** da narração (substring normalizada); `lead_ms` default por `do` (reveal 120, count 200, emphasis 0, cut −40).
- `render.py`: o atraso do `.rv` (`data-d`, hoje fixo, `render.py:75`) passa a vir do cue: `delay = t(on) − lead_ms − scene_start`. Sem cues → comportamento atual (golden test). Ease por tipo de beat (entrada ease-out, saída ease-in), `stagger` 40–80 ms para listas.
- `pause_after_s` por cena e `[beat]` na narração → pausa (0,35–0,6 s) inserida no áudio: o TTS não lê `[beat]` (removido antes da síntese e convertido em silêncio com **room tone** de baixo nível, nunca silêncio digital).
- J/L-cut opcional por cena: `audio_lead_s` (0–0,4 s) deixa a voz da cena seguinte entrar antes do corte; ajustar `narration_cues` (hoje a voz nunca começa antes da cena, `render.py:~383`).
- Lints novos: `cue_unmatched` (`on` não está na narração), `cue_late` (cue depois do fim da fala), `density_overload` (>3 cues na mesma frase).
- `verify` reporta `cues: {n, matched, align, max_err_ms}`.

**Arquivos:** `tts.py`, `spec.py` (schema, `timeline` para `pause_after_s`), `render.py` (template JS + áudio), `audio.py` (room tone/pausa), testes + novo `tests/test_cues.py`, `test_render_e2e.py` (golden).

**Verificação adversarial:**
| Ataque | Detecção | Mitigação |
|---|---|---|
| Alinhamento errado → o reveal cai **depois** da palavra (pior que sem cue) | teste de contrato: para frases sintéticas com palavra em instante conhecido, erro < limite; vídeo de referência com 5 cues revisados à mão (frame vs onda) | `lead_ms` mínimo conservador; se `align=="estimated"` e erro p95 alto → o lint avisa e o render mantém o fallback sem cue |
| Trecho `on` ambíguo (palavra aparece 2 vezes) | teste | exigir trecho único; senão `cue_unmatched` com `fix: use a trecho mais longo` |
| Normalização de texto: `pronounce()` troca "LD_PRELOAD"→"el di preload" antes do TTS; o cue procura o texto original | teste com `say` | casar contra o texto **falado** (`man.scenes[id].text`, já salvo) e mapear de volta |
| Cue em cena que depois mudou de duração (re-narração) | editar linha e rodar de novo | cues são recomputados no `narrate`; `resolved_hash` já muda com o áudio |
| Trocar `data-d` fixo quebra render antigo | golden: spec sem cues, `digest` de stills idêntico ao "antes" | caminho antigo preservado; flag interna |
| Frame rate: lead em ms vs frames | testar 24/30/60 fps | converter `lead_ms → frames = round(ms*fps/1000)` sempre pelo `fps` do spec; teste parametrizado |
| Música depois da voz muda a leitura percebida | revisão no mix | rodada "fine cut" assiste com mix, em notebook e celular |
| Room tone inventado soa artificial | escuta A/B | ruído rosa −60 dBFS filtrado, só na pausa; preferir trecho do próprio WAV se houver |
| Complexidade de `render.py` (643 linhas) | revisão de diff | extrair cálculo de cues para `cues.py` puro e testável; `render.py` só consome |

**Pronto quando:** erro mediano de alinhamento ≤ 80 ms no corpus; spec sem cues = frames idênticos; 5 cues na referência revisados à mão ≤ 1 frame de erro percebido; `verify` mostra `max_err_ms`.
**Rollback:** cues ignorados por flag `STORYBOARD_CUES=0`; manifesto com `words` é aditivo.

---

# Fase 4 — som: −14 LUFS, SFX (music-search `--kind sfx` + síntese), room tone

## 4a. Loudness −14 web
- `audio.py`: `TARGET_I` deixa de ser constante global; `spec.audio.target_lufs` (default **−14**, faixa permitida −24…−12). `TARGET_TP` e `TP_LIMIT` passam a −1.5/−1.0? **Decisão:** para −14, usar `TP = −1.5` no alvo do loudnorm e `TP_LIMIT = −1.0` no verify (AAC overshoot). Medir antes na referência (Spike 4a).
- Risco técnico **[?]**: `loudnorm linear=true` só funciona se o ganho necessário não estourar o TP; com voz + música a −14 pode forçar modo dinâmico (bombeamento). Mitigação: `alimiter` antes do 2º passe e teste na referência (LRA e picos).
- `resolved_hash`: incluir `target_lufs` e `AUDIO_VERSION` para invalidar renders cacheados (**[C]** hoje não entra).
- `loudness_findings`: usa o alvo do spec; mensagem "−14 LUFS ±1,5".
- `credits`, SKILL.md linha 67 e README: −14.
- Testes: atualizar `test_audio.py:72,95`, `test_audio_mux.py:162,186`; novo teste parametrizado para −16 e −14 e para alvo inválido (`error`).

## 4b. Música depois da voz
Fluxo: lock de voz → `music-search --duration <total>` e `--bpm`/vibe da cadência → stage → `spec.music`. Guardrail: se o spec tem `music` mas nenhuma `narrate`, `warn music_before_voice`.

## 4c. SFX: duas fontes, nenhum pacote no repo
**Fonte 1 — síntese procedural (default, licença limpa):** `sfx.py` gera com ffmpeg/`lavfi` (`sine`, `anoisesrc`, envelopes `afade`, `lowpass/highpass`) os tipos `tick`, `whoosh` (ruído com varredura de filtro), `hit` (queda de pitch), `pop`. Determinístico (semente fixa), cache por parâmetros, saída WAV 48 kHz −24 dBFS. Licença: gerado, sem terceiros → nada a creditar.
**Fonte 2 — `music-search` com `--kind sfx`:** a skill já tem pipeline de licença (allowlist CC0/CC BY, negação de Freesound, sidecar com `license_evidence`, verificação de origem `origin_verify_failed`). Estender:
- `--kind music|sfx` (default music), `--category sound_effect` quando a fonte suportar **[?]** (spike: confirmar se Openverse audio aceita filtrar efeito sonoro; senão filtrar por tags `sfx|sound effect|whoosh|click`).
- Fontes SFX candidatas a validar licença e ToS **uma por uma** antes de ligar: Openverse (já), Internet Archive (já), OpenGameArt (CC0 packs), Kenney (CC0), ccMixter (poucos). Freesound **segue negado**. Pixabay/Mixkit/Sonniss: licença própria não-CC → negadas por padrão (nada a defender a um revisor, regra existente).
- Para SFX o gate é mais rígido: **CC0 apenas** (CC BY exige crédito por efeito de 0,3 s; custo/benefício ruim) → `sfx_license_denied` para o resto.
- Duração: `--max-s 3`; sem loop, sem fade longo; trim automático ao pico.
**Como entra no spec:** `scene.sfx: [{"at": "cue:N" | seconds, "kind": "tick"|..., "path": "/music/sfx/<id>.wav" (opcional), "gain_db": -14}]`. Sem `path` → síntese. `audio.build` mixa os SFX sobre o bed/voz com ganho fixo (SFX −10 dB da voz, **fora** do sidechain: não é duckado nem key do duck, ou o duck pulsa a cada clique).
**Créditos:** SFX CC0 ainda são listados em `CREDITS.txt` (origem+licença) por rastreabilidade, sem obrigação.

## 4d. Qualidade de mix
`verify`: pico, `duck_margin_db` (voz ≥ 8 dB acima do bed durante fala, medido por janelas), silêncio. Room tone da Fase 3 reutilizado.

**Arquivos:** `audio.py`, novo `sfx.py`, `spec.py` (schema `audio`, `sfx`), `render.py` (hash), `skills/music-search/SKILL.md` + `scripts/`, `tests/test_audio*.py`, novo `test_sfx.py`, `test_music_bed.py`.

**Verificação adversarial:**
| Ataque | Detecção | Mitigação |
|---|---|---|
| −14 + TP leva a normalização dinâmica/pumping | medir LRA e histograma na referência; comparar áudio do passo 1 e 2 | limiter antes do 2º passe; se ainda falhar, alvo −15 com aviso |
| Cache servindo mix −16 | trocar o alvo e re-renderizar, checar `resolved_hash` mudou | `target_lufs` e `AUDIO_VERSION` no hash; teste |
| SFX duckam a cama ou disparam o sidechain | espectro/loudness com e sem SFX | SFX mixados depois do duck |
| SFX sintetizados soam "de brinquedo" | escuta A/B com 3 referências | só `tick`/`whoosh` suaves por default; `sfx` desligável (`audio.sfx:false`); ausência de SFX nunca é erro |
| Licença de SFX baixado de fonte duvidosa | auditar sidecar de 10 candidatos | só CC0 + `license_evidence` literal + `sha256`; Freesound negado; qualquer dúvida → síntese |
| Ataque ao `music-search`: URL redireciona para outro arquivo/licença | já coberto por `origin_verify_failed`; replicar teste para `--kind sfx` | reutilizar o mesmo código de verificação, sem fork |
| SFX em excesso (cliques em tudo) | contar SFX/min na referência | lint `sfx_density` (> 1 por 2 s → warn) |
| Música escolhida depois quebra a duração (`fetch` precisa do total) | e2e | total é conhecido após lock; teste |
| Rate-limit/offline nas fontes | simular HTTP 429 | resultado `error`, fallback síntese (já é o desenho do skill) |

**Pronto quando:** referência mede −14 ±1,5 LUFS, TP ≤ limite, LRA razoável; trocar alvo muda o hash; SFX sintético reproduzível (mesmo WAV byte a byte); music-search `--kind sfx` rejeita 100% de candidatos não-CC0 no teste.
**Rollback:** `audio.target_lufs: -16` restaura o comportamento antigo por spec; SFX é opt-in por cena.

---

# Fase 5 — cutdowns, rodadas e entrega

- `cutdown(spec_hash, target_s, placement)`: reaplica o arco com orçamento menor (preserva `hook`, `reveal/value` principal, `result`, `cta`; descarta `implication` e `value` secundário), gera novo `spec_hash`, devolve `removed: [{scene, motivo}]`. **Nunca** acelera a voz para caber: corta cena.
- Ad 15–30 s: hook ≤ 3 s, mensagem inteira em texto na tela (funciona mudo), sem música obrigatória.
- `reframe` (aspecto) continua; cutdown + reframe compõem.
- Rodadas: `/work/rounds/<n>.md` com pergunta, notas (timecode, must/pref), decisão, `spec_hash` antes/depois. Ferramenta `round_log(...)` mínima ou instrução no SKILL.md (decidir no PR: se ninguém consome, fica como template de texto, não ferramenta).
- Nomes de entrega: `<projeto>_vNN_<aspecto>_<AAAA-MM-DD>.mp4`, `CURRENT` aponta o último, antigos em `archive/`.
- Delivery check (rodada 4): ortografia (texto de tela vs narração via `evidence`), níveis (`verify`), formatos, legendas SRT, `CREDITS.txt`, licenças.

**Verificação adversarial:**
| Ataque | Detecção | Mitigação |
|---|---|---|
| Cutdown remove a prova e deixa promessa sem lastro | `hook_promise_unkept` no cutdown | cutdown mantém hook+proof pareados ou falha explicando |
| Cutdown muda `spec_hash` e perde os cues/narração em cache | e2e | reutilizar cache de linhas; cues recomputados |
| Cutdown de 15 s inviável (hook+cta já > 15 s de fala) | teste com spec longo | erro `cutdown_infeasible` com `min_s` |
| Explosão de arquivos de rodada | contagem | só 1 arquivo por rodada, sem anexos |
| Arquivo `CURRENT` desatualizado | teste | atualizar atomicamente no mesmo comando de render |

**Pronto quando:** de um master de 60 s saem 30 s e 15 s que passam `validate_spec`, `verify` e a lente "espectador frio" sem nota must-change.

---

# Riscos de integração e ordem de merge
1. **Ordem:** F1 → F0 (texto referencia roles/lints) → F2 → F3 → F4 → F5. Fase 0 sobre loudness **só** muda o número no mesmo PR da Fase 4; antes disso o SKILL.md continua dizendo −16 (senão a doc mente por semanas).
2. **Hash:** F3 (cues, pausa) e F4 (alvo, SFX) alteram saída → bump de `RENDER_VERSION`/`AUDIO_VERSION` na mesma fase que mudar bytes.
3. **Tests-as-doc:** cada exemplo novo no SKILL.md entra em `test_skill_docs.py`.
4. **Imagem Docker:** F3 pode acrescentar dependência (faster-whisper): medir tamanho/tempo de build; preferir alternativa B se equivalente.
5. **Delegação (AGENTS.md):** lentes de revisão e spikes de pesquisa (fontes SFX, Openverse) vão para subagentes read-only; implementação fica na thread principal. Nunca dois editando `spec.py`.
6. **Verificação transversal por PR:** (a) suíte verde no container; (b) `storyboard-e2e.sh`; (c) vídeo de referência antes×depois, com `digest` de stills idêntico quando o spec não usa recurso novo; (d) um revisor frio lê só o diff e tenta quebrar (spec malformado, `lang` ausente, `fps` 24/60, aspecto 9:16, cena sem narração, cena única).

## Matriz de adversarial transversal (rodar em toda fase)
| Entrada hostil | Esperado |
|---|---|
| spec legado sem `direction` | renderiza igual, 0 findings novos |
| `direction.scenes` com id inexistente | `warn`/`error` já existente, sem traceback |
| `cues` com `on` vazio / enorme / unicode (pt-BR com acento) | `error bad_cue` ou `cue_unmatched`, sem crash |
| narração com `[beat]` no fim ou duplicado | pausa única limitada (≤ 1 s) |
| 9:16 com callouts longos | `layout` já audita; `callout_too_long` coerente |
| alvo de loudness absurdo (−5, −40) | `error bad_audio`, nunca clip |
| música ausente / path fora de `/music` | silêncio, sem falha (comportamento atual preservado) |
| SFX com path fora da allowlist | `PermissionError` via `safe_path`, vira finding |

## Estimativa grosseira (esforço relativo, não prazo)
F0 S · F1 M · F2 M · F3 L (com spike) · F4 L (música/SFX/loudness) · F5 M.

## Perguntas ainda abertas (não bloqueiam F0/F1)
1. Spike F3: B (estimado) suficiente ou exige whisper no container?
2. Spike F4: Openverse filtra `sound_effect`? Quais fontes CC0 de SFX passam na revisão de ToS?
3. ~~Vídeo de referência~~: decidido, `../mint`. Pendente: gerar o spec "antes" com o fluxo atual (exige build de `mint_loader` no container).
