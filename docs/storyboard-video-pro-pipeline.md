# storyboard-video: pipeline profissional (pesquisa + desenho de implementação)

Data: 2026-10-30. Escopo: o que falta para o vídeo sair em nível profissional. Base: pesquisa web (fontes no fim) + leitura de `skills/storyboard-video/SKILL.md`, `storyboard_video_mcp/{spec,render,audio}.py`.

Legenda: **[F]** = vem de fonte citada; **[C]** = confirmado no código; **[K]** = conhecimento do ofício, sem fonte fetchada (validar antes de virar regra dura).

---

## 1. Como um estúdio faz (e por quê)

### 1.1 Ordem de trabalho = ordem de custo de mudança [F]
estratégia → roteiro → **scratch VO** → **animatic** → aprovação → VO final → edição → **picture lock** → (animação fina | cor | som | mix em paralelo) → entrega.
Regra de ouro: a narração é o relógio mestre; dá para segurar um gráfico 6 frames, não dá para fazer o narrador falar 400 ms mais rápido. Reentrega de áudio depois da animação é "o erro de timing mais caro". O animatic é onde mudar o roteiro custa minutos, não dias.

### 1.2 Rodadas de revisão com propósito [F]
| Rodada | Pergunta única | Proibido comentar |
|---|---|---|
| 1 Rough cut | A história funciona? Falta algo? | cor, música, gráficos (provisórios) |
| 2 Fine cut | Segura? Duração certa? | acabamento |
| 3 Lock candidate | Última mudança barata | — |
| 4 Delivery | Ortografia, níveis, formatos, legal | criativo |
Notas sempre com timecode, descrevem o problema (não a solução), separam must-change de preferência, uma voz só consolida. Versões numeradas, um único link "atual", obsoletas arquivadas. Oito rodadas = briefing ruim.

### 1.3 Estrutura narrativa [F]
- Explainer (6 partes): Hook, Problema, Implicação, Solução, Resultado, Close.
- Demo B2B (4 partes): Hook (0–15 s) → Problema (15–45 s) → Solução com **um** workflow completo → Prova + **um** CTA (15–30 s).
- StoryBrand SB7: herói = espectador, produto = guia; personagem, problema, guia, plano, CTA, evitar fracasso, sucesso.
- Vídeo curto: comprime os atos, mas "ainda precisa dos três" (problema, soluções, benefício/CTA).
- Problema primeiro, produto depois. Sem logo/saudação/intro de marca nos primeiros segundos. Especificidade > completude (um fluxo bem mostrado vence dez features). Linguagem do cliente, não do produto. Cortar "poderoso/seamless/robusto" e "agora vamos para…".

### 1.4 Hook [F]
Decisão de ficar acontece em ~3 s; o **primeiro frame** dispara antes da primeira frase (muito consumo é mudo). 5 arquétipos: curiosity gap, bold claim (falsificável), social proof (número oddly specific), pattern interrupt, stakes/loss. Os bons empilham dois (imagem mostra a anomalia, voz dá o porquê). Escrever ~10 hooks, filmar 2, medir. Cold open no melhor momento da captura, depois contexto.
Aviso das próprias fontes: curiosity gap falso = clickbait; o hook é uma promessa que o resto tem obrigação de cumprir.

### 1.5 Script em duas colunas (AV) [F]
Uma linha por momento: **áudio exato** de um lado, **visual** do outro, tempo acumulado embaixo. Direção fora do texto falado. Números e lower thirds escritos exatamente como aparecem. Planejar a 150 wpm = 2,5 palavras/s (faixa 130–170); o tempo real vem da gravação. 190 palavras em 60 s = cortar palavras, não pedir leitura mais rápida.

### 1.6 Sincronia imagem/voz [F]
- Visual chega **na** palavra ou um pouco **antes**, nunca depois (atraso lê como desleixo).
- Marcadores nas 1–3 palavras-chave por frase, no ataque da consoante, nomeados por **ação** ("logo entra", "gráfico cresce"), não pela palavra.
- Lead em **milissegundos**, não frames (4 frames = 167 ms a 24 fps, 67 ms a 60 fps).
- Corte seco: na palavra ou 1–2 frames antes. Reveal com ease: começa antes para estar legível quando a palavra cai. Contador: começa antes, termina no número falado. Movimento de câmera: dentro da pausa antes do novo ponto. Pulso de ênfase: na sílaba tônica.
- Uma mudança visual principal por frase; duas se for longa; três sobrecarrega. Texto na tela precisa de tempo de leitura enquanto a voz segue.
- Pausa a cada mudança de tópico, maior entre seções; a transição acontece **no silêncio**. Pausa lengthened com room tone, não silêncio digital. Marcar `[beat]` no roteiro.
- Checar timing contra o **mix**, não contra a voz seca (música mascara finais de palavra; SFX vira o ponto de sync percebido). Conferir em notebook e celular.

### 1.7 Edição e densidade [F]
Nenhum plano > 5 s sem corte, anotação ou mudança. J-cut / L-cut para continuidade de áudio entre cenas. Callouts ≤ 8 palavras, mesmo estilo, animados dentro e fora (não "pop"). Zoom 125–150% em interação importante. Estado limpo (sem notificações, abas), **dados realistas** (nada de "Company A / Test Account"). Gravar a 2x e desacelerar 50% para cursor suave. Funcionar sem som (texto e UI claros). Comprimento por colocação: ad 15–30 s, hero 60–90 s, landing 2–3 min; cortes diferentes por canal, não um master reaproveitado. 1 CTA só.

### 1.8 Som [F/K]
Áudio ruim derruba mais que imagem ruim [F]. Normalização online ≈ −14 LUFS [F]; broadcast EBU R128 −23, ATSC A/85 −24 [F]. Música com tempo compatível com a leitura; alguns estúdios escolhem a música **depois** de travar a voz [F]. SFX atrelado a cada reveal/clique [K]. Ducking sidechain da cama sob a voz [K, e já existe no código].

### 1.9 Motion [K, parcialmente F]
Timing, easing, hierarquia, restrição, propósito. Uma família de easings para tudo; entrada ease-out, saída ease-in; staggering curto (30–80 ms) entre itens de lista; hierarquia por tamanho/peso, não por movimento; movimento só quando comunica algo.

---

## 2. O que a skill faz hoje [C], por camada

| Camada | Hoje | Lacuna vs. profissional |
|---|---|---|
| Estratégia | Entrevista (8 perguntas, sobretudo config); `purpose` e `tone` | Falta público, dor em 1 frase, mensagem única, ação desejada, linguagem do cliente |
| Narrativa | `direction.scenes[id].role ∈ {hook,problem,reveal,value,proof,cta}` existe em `spec.py:31`, mas só valida o **tipo**; "5–7 cenas, 30–45 s" | Nenhuma exigência de arco: pode passar sem `hook`, sem `problem`, sem `cta`. Cenas nascem das *features* do README, não de beats |
| Hook | Cena `title` | Sem promessa obrigatória, sem arquétipo, sem teste mudo do 1º frame, sem alternativas |
| Roteiro | Tabela cena / texto na tela / fonte | Sem coluna de áudio+visual lado a lado, sem tempo acumulado, sem `[beat]` |
| Scratch/animatic | Não existe. `narrate` só depois de stills aprovados; `draft` é um render completo | Ninguém ouve o ritmo antes de capturar; captura (cara) vem antes do ritmo (barato) |
| Relógio mestre | Parcial e bom: cena dura `max(duration_s, áudio + 0.4 s)`; `duration_s` é chutado antes da voz | Duração deveria **derivar** da voz, não ser palpite |
| Sincronia | Reveal `.rv` por delay fixo; todos entram com o mesmo ease (`render.py:56,75`); crossfade sem sobreposição | Nenhum elemento é amarrado a uma palavra; sem marcadores; sem lead; sem J/L-cut (voz só começa com a cena) |
| Densidade | `max_words_card`, `narration_pace` (>3,2 pal/s), lints de layout | Sem limite de plano parado (5 s), sem "uma mudança por frase", sem limite de palavras por callout, sem checagem de variação de ritmo |
| Som | Cama + ducking por sidechain + loudnorm 2 passes em **−16 LUFS** (`audio.py`) | Sem SFX; sem room tone nas pausas; alvo −16 vs −14 não decidido; música escolhida antes da voz |
| Motion | `motion: still|subtle|lively`, ease cúbico único, settle 0,8 s | Uma curva só; sem stagger; sem saída diferente de entrada; sem variação por papel (hook ≠ proof) |
| Revisão | 4b: revisor "fresco" checa verdade/curto/falável | Não checa história, hook, ritmo, "e daí?"; não há rodadas com escopo; notas sem timecode; sem versionamento além do `spec_hash` |
| Entrega | `verify`, WER faster-whisper, licenças | Muito acima do comum. `reframe` só muda **aspecto**, não **duração/colocação** (sem cutdown 15 s / 90 s) |
| Honestidade | `evidence` file:line, nada inventado | Diferencial real; preservar |

Correção ao que eu disse antes: o enum de `role` **já existe** e o mix é bem melhor do que "fraco" (ducking + loudnorm). Os furos reais são o arco não exigido, a ausência de animatic e de sync por palavra.

---

## 3. Desenho alvo

### 3.1 Fluxo novo (substitui os passos 3–7 do SKILL.md)

```
 1 preflight
 2 scan_repo + brand_tokens
 3 BRIEF (substitui a entrevista longa; 5 perguntas de conteúdo + 3 de config)
 4 DIRECTING  -> direction.md (pesquisa -> ARCO escolhido, não só URLs)
 5 LOGLINE + 2 ARCOS (escolha do usuário)             [gate 1]
 6 HOOKS: 5–10 candidatos, 2 finalistas, usuário escolhe  [gate 1b, mesmo gate]
 7 AV SCRIPT (duas colunas, tempo acumulado, [beat])   [gate 2: aprovação]
 8 SCRIPT REVIEW adversarial (§3.4)
 9 SCRATCH VO (TTS) -> ANIMATIC: cartões/placeholders + voz, sem captura final [gate 3: rough cut]
10 CAPTURE só do que o animatic confirmou (shot list gerada do AV script)
11 FINE CUT: stills + cues alinhados à voz                  [gate 4]
12 LOCK: spec_hash congelado, voz final, marcadores gerados
13 RENDER delivery + mix + SFX + verify + WER
14 DELIVERY CHECK (rodada 4: ortografia, níveis, formatos, licenças)
15 CUTDOWNS do master travado (15–30 s, 60–90 s, 9:16)
```
Regra de rodada: cada gate anuncia a pergunta única da rodada e o que **não** será julgado (§1.2).

### 3.2 Brief (passo 3) — perguntas
Conteúdo: (1) quem assiste e em que situação; (2) a dor em uma frase, nas palavras dele; (3) o que ele deve fazer depois (um CTA); (4) a única mensagem; (5) onde toca (hero, ad, deck, booth): define duração e se precisa funcionar mudo.
Config: formato/aspecto, idioma+voz, música (vibe ou nenhuma), paleta/tom com referência.
Saída: `/work/brief.md` com `audience`, `pain`, `promise`, `cta`, `placement`. Fonte para linguagem do cliente: README, issues, mensagens de commit/CHANGELOG (o que o repo diz sobre o problema).

### 3.3 Arcos (passo 5) — gabaritos por duração/placement
Mapeados no enum que já existe; acrescentar `implication` e `result` só se a decisão §5.1 for sim.

| Placement | Duração | Beats e orçamento (% do tempo) |
|---|---|---|
| ad / loop | 15–30 s | hook 15 · problem 20 · reveal 35 · proof 15 · cta 15 |
| hero / feature demo | 45–90 s | hook 12 · problem 20 · reveal 10 · value (1 workflow completo) 40 · proof 10 · cta 8 |
| landing / walkthrough | 2–3 min | idem, value pode ter 2–3 passos com capítulos |
(percentuais [K]; calibrar com 3–5 vídeos de referência antes de virar lint duro).

Cada cena do plano ganha `beat` (= `role`), `promise` (o que o espectador sabe/sente ao sair da cena), e `visual_change_per_sentence`.
Antes/depois explícito é **obrigatório** em `reveal` ou `value` (§1.7).

### 3.4 Revisão adversarial (passo 8) — papéis que tentam quebrar o vídeo
Hoje há um revisor; passar a ter 3 lentes independentes (subagentes read-only, fresh context, mesmo input), cada um devolve veredito por linha com **timecode/cena**:

1. **Espectador frio** (só vê o AV script e o 1º frame, sem README): "o que é isso, para quem, por que eu ligo?" Falha se não souber em 10 s. Teste do 1º frame **mudo**.
2. **Cético** (caça claim sem prova): cada afirmação ↔ `evidence`/captura; promessa do hook cumprida? outro sai contradizendo o footage? (já é o 4b atual, mantido).
3. **Editor** (ritmo): mapa de densidade (palavras/s por cena, duração por cena, tipo de cena); aponta 3 cenas seguidas iguais, plano > 5 s sem mudança, texto sem tempo de leitura, ausência de pausa nas trocas de tópico.
O orquestrador consolida em **uma lista** (must-change vs preferência), com timecode, e só então reescreve. Máximo 2 ciclos; se o revisor 1 ainda falhar, volta ao arco, não à frase.

### 3.5 Animatic (passo 9)
- Cada cena do AV script vira cartão simples (`title`/`bullets` ou captura placeholder = frame do `scan_repo`/screenshot existente) + `narrate` com TTS **só como estimativa de duração** (a fonte avisa: TTS é regular demais; vale para estrutura, não para timing fino).
- `draft` rápido (baixa resolução) → o usuário lê ritmo em um clip curto. Rodada 1: estrutura apenas.
- Só depois disso o `capture_*` roda. Shot list = coluna "visual" do AV script, cena a cena, com o tempo que a voz deixou para ela (o capture grava exatamente o necessário).

### 3.6 Spec — campos novos (retrocompatíveis; `spec.py`)
```jsonc
"direction": { "brief": {"audience":"…","pain":"…","promise":"…","cta":"…","placement":"hero"},
               "arc": "hero-4part", "hook_archetype": "stakes" },
"scenes": [{ "id":"hook", "beat":"hook",              // = role; validar contra o arco
  "narration":"…[beat]…",                             // [beat] vira pausa de 0.35–0.6 s
  "cues":[ {"on":"perdendo horas","do":"reveal","target":"caption","lead_ms":120},
           {"on":"3 comandos","do":"count","target":"num0","lead_ms":200} ],
  "pause_after_s": 0.5,
  "sfx":[{"at":"cue:0","kind":"tick"}] }]
```
- `cues[].on`: **trecho da narração**. O tempo vem de timestamps por palavra do WAV (faster-whisper com `word_timestamps`, já disponível no ambiente; Kokoro pode não expor timings — checar `tts.py`). Resultado gravado no manifesto de `narrate` (`words:[{w,start,end}]`).
- `render.py`: substitui o delay fixo `.rv data-d` pelo tempo do cue − `lead_ms`; ease por tipo de beat (§1.6); fallback para o comportamento atual quando não há `cues` (nada quebra).
- `pause_after_s` e `[beat]`: o áudio já é montado por cena (`render.py ~377`), então inserir silêncio com room tone é mudança local em `audio.py`.
- Lints novos em `validate_spec` (todos `warn` na v1, promover a `error` com dados):
  `arc_missing_beat` (hook, problem, cta ausentes) · `hook_not_first` · `hook_brand_first` (logo/saudação/nome do produto nas 1ªs 2 palavras ou 1ºs 3 s) · `hold_too_long` (cena parada > 5 s sem cue/mudança) · `callout_too_long` (> 8 palavras) · `density_overload` (> 3 mudanças por frase) · `monotone_pace` (3 cenas seguidas mesmo tipo e duração ±15%) · `cue_unmatched` (texto de `on` não existe na narração) · `silent_unreadable` (cena com texto tem tempo de leitura < palavras/ 3 por s) · `no_before_after`.

### 3.7 Som
- Decisão de alvo: **−14 LUFS integrado, TP −1** para web/hero; manter −16 como opção (`audio.target_lufs`). Hoje `audio.py:TARGET_I` é fixo. `[C]`
- SFX: conjunto mínimo (tick, whoosh curto, hit leve) licenciado CC0, em `/music/sfx/` com mesma trilha de sidecar de licença da música. Sem biblioteca licenciada = sem SFX (nunca improvisar). Cada SFX preso a um cue.
- Música: só **após** travar a voz (mudança na ordem do SKILL.md: `music-search` passa a rodar no passo 12, com BPM/vibe conhecidos da cadência da leitura).
- Room tone: 1–2 s de ruído de fundo extraído de gap do TTS ou gerado baixo, preenchendo pausas; nunca silêncio digital.
- Verificação: `verify` já mede LUFS; adicionar pico e checagem de duck (voz ≥ 8 dB acima da cama durante fala) [K].

### 3.8 Motion
Um único preset de easing por vídeo (ease-out entrada, ease-in saída), stagger 40–80 ms para listas, saída curta (≈ 0,25 s) antes do corte, J-cut opcional (`audio_lead_s` 0–0,4 s: a voz da cena seguinte entra antes) e L-cut (`audio_tail_s`). `motion: lively` continua existindo, mas o default passa a respeitar "restrição": sem escala contínua.

### 3.9 Cutdowns (passo 15)
`reframe` já existe para aspecto. Novo `cutdown(spec_hash, target_s, placement)`: reaplica o arco com orçamento menor (descarta `implication`/`value` secundário, mantém hook+reveal+cta), gera novo `spec_hash`, lista cenas removidas. Ads de 15–30 s: hook nos primeiros 3 s, texto carrega a mensagem inteira (mudo por padrão).

### 3.10 Versionamento e relatório de rodada
`spec_hash` já é a versão. Acrescentar `/work/rounds/<n>.md`: rodada, pergunta, notas (timecode, severidade must/pref), decisão, `spec_hash` antes/depois. Nome de artefato: `project_vNN_aspect_YYYY-MM-DD.mp4`; um `CURRENT` aponta para o último; antigos vão para `archive/`.

---

## 4. Faseamento

| Fase | Entrega | Arquivos | Risco |
|---|---|---|---|
| 0 | Reescrever SKILL.md: brief, arcos, hooks, AV script, revisão adversarial, rodadas, ordem música-após-voz | só `SKILL.md` | baixo |
| 1 | Lints novos (`arc_missing_beat`, `hook_*`, `hold_too_long`, `callout_too_long`, `monotone_pace`, `silent_unreadable`) em `warn` + testes | `spec.py`, `tests/` | baixo |
| 2 | Animatic: `narrate` permite `scratch=true` (cartões + TTS) e `draft` baixa res; shot list gerada do AV script | `server.py`, `render.py` | médio |
| 3 | Cues por palavra: `narrate` grava timestamps por palavra; `render.py` consome `cues` | `tts.py`/`audio.py`, `render.py`, `spec.py` | **alto** (sync é o núcleo) |
| 4 | Som: alvo configurável, room tone, SFX licenciados, J/L-cut | `audio.py`, `render.py` | médio |
| 5 | Cutdown e relatório de rodadas | `server.py`, SKILL.md | baixo |
Cada fase termina com um vídeo de referência (mesmo repo de demo) para comparar antes/depois e subir os lints de `warn` para `error` onde os dados sustentarem.

## 5. Decisões abertas (precisam do usuário)
1. Adicionar `implication`/`result` ao enum de `role` ou manter 6 beats?
2. Alvo de loudness padrão: −14 (web) ou manter −16?
3. SFX: aceitar um pacote CC0 pequeno incluído no repo, ou sem SFX?
4. O animatic vale o custo extra de uma rodada TTS extra por vídeo (cache por linha já existe)?
5. Fase 3 (sync por palavra) via faster-whisper word timestamps (mais portátil) ou via timings do Kokoro (se expostos)?

## 6. Riscos do próprio desenho (adversarial)
- **Excesso de gates**: 4 pausas para o usuário num vídeo de 45 s é fricção. Mitigar: gates 1+1b+2 viram uma só mensagem; modo `--fast` pula animatic e rodadas 1–2 (mas mantém lints e revisão).
- **Arco por template vira vídeo igual**: percentuais são ponto de partida; o brief (dor + linguagem do cliente) é o que diferencia. Revisor "espectador frio" existe para pegar template genérico.
- **Hook forte sem prova = clickbait**. Lint `hook_promise_unkept`: promessa do hook precisa ter cena `proof`/`value` com `evidence` ou captura correspondente. Manter a regra "nunca afirmar o que não capturou".
- **TTS como régua**: fonte avisa que a cadência é regular demais; usar só para estrutura, rechecar com a voz final e com WER (já no fluxo).
- **Lints viram teatro**: números (5 s, 8 palavras, 3 mudanças/frase) vêm de guias de marketing, não de estudos; começam como `warn` e só viram erro com dados reais.
- **Percentuais de arco e lead_ms** são [K]/heurísticas; calibrar em vídeos de referência.
- **Música depois da voz** muda o fluxo atual (`music-search` hoje roda antes); checar que o `duration` do `fetch` ainda é conhecido nesse ponto (sim, após lock).

---

## Fontes consultadas
- Superside, Video project workflow — https://help.superside.com/en/articles/13843140-video-project-workflow
- Ziflow, Video production workflow — https://www.ziflow.com/blog/video-production-workflow
- Grumo Media, 5 parts every explainer script needs — https://grumomedia.com/5-parts-every-explainer-video-script-needs/
- Clint Neilsen, Explainer script (6 partes) — https://clintneilsen.com/the-ultimate-guide-to-writing-a-killer-explainer-video-script/
- Motion University, 3-act structure in promo films — https://blog.motionuniversity.org/pre-production/using-the-3-act-story-structure-in-promo-films/
- StoryBrand SB7 (Salt Marketing, Southend, Blare) — https://saltmarketing.co/brand-video/ · https://www.southendproductions.com/blog/using-the-storybrand-framework-in-video-marketing
- Boords / RecReview, AV script de duas colunas — https://boords.com/video-script-template · https://rec.review/en/blog/video-script-template
- FrameJam, palavras por minuto — https://www.framejam.ai/guides/explainer-video-words-per-minute
- MediaScaleUp, Animating to voiceover — https://mediascaleup.com/post/animating-to-voiceover-done-properly-motion
- Storyflow, Review rounds — https://storyflow.so/blog/managing-video-project-with-a-team-review-rounds-versions-2026
- Video Editing Company, Product demo best practices 2026 — https://videoeditingcompany.com/product-demo-video-best-practices/
- JML Tech Studios, First 3 seconds — https://www.jmltechstudios.com/blog/video-hooks-first-3-seconds
- PremiumBeat (Felipe Salazar), Avid, postPerspective — animatic/scratch dialogue em animação
- HEY JOE, Editing fundamentals (J/L-cut) — https://heyjoeav.com/en/tips/editing-fundamentals

Não obtidos (provedor falhou/403): fontes sobre princípios de motion (madegooddesigns 403) e loudness/ducking; esses itens estão marcados [K].
