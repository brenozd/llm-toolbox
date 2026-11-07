---
name: openscad-part
description: "Modela uma peça imprimível em FDM do zero: entrevista, spec em mm, .scad com inputs mínimos e revisão automática (malha, bbox, volume, overhang) mais um revisor adversarial. Use for: \"modela essa peça\", \"faz um suporte pra\", \"peça em openscad\", /openscad-part."
metadata:
  version: "0.1.0"
---

# openscad-part

Uma peça por vez, em 4 fases, **com gate de confirmação do usuário entre elas**.
Não pule um gate: cada fase termina com uma pergunta curta e você só continua
depois do "ok".

Artefatos (todos ao lado do `.scad`, `out/` é ignorado pelo git):

```
peca/
  peca.scad        # o modelo — só ele é fonte de verdade
  spec.md          # parâmetros, interfaces, critérios, log de revisão
  out/             # STL, echo, PNGs e a saída do review.py
```

## Fase 1 — Entrevista

Entreviste como em `skills/grilling/SKILL.md`: uma rodada por vez. Se houver
ferramenta de perguntas estruturadas (`ask_user_question`), use-a (opção
recomendada primeiro, marcada "(Recomendado)" no idioma do usuário). Só sem ela,
use o formato

```
❓ **Q1** - **<título>**: <pergunta>

➡️ <sua recomendação>
```

Fatos (medidas do ambiente, specs de parafuso, dimensões de um objeto que está
no disco) são **seus**, buscados por subagente — nunca pergunte ao usuário o que
dá para descobrir. As decisões são dele.

Cubra, no mínimo:

- **Função** — o que a peça resolve; o que acontece se ela falhar.
- **Interfaces** — o que encaixa onde, com que folga, e se é encaixe
  permanente, deslizante ou apertado.
- **Medidas** — quais foram medidas (e com o quê) e quais são assumidas.
- **Bico e material** — 0.4 mm / PLA se ele não souber; afeta parede e furo.
- **Tolerância de encaixe** — 0.1 aperto · 0.15–0.25 deslizante · 0.3 folgado.
- **Orientação de impressão** — onde fica a base, o que vira overhang.
- **Carga/uso** — quantas peças, esforço, exposição (sol, calor).

## Fase 2 — Spec

Copie `templates/spec.md` para `spec.md` e preencha. Regras:

- Unidade **mm**, sempre.
- Todo parâmetro tem **origem**: `medido` ou `assumido` (assumido leva o risco
  na nota).
- Tolerâncias fixas de gate: bbox **±0.1 mm**, volume **±1 %**.
- Separe os critérios em **verificados por `review.py`** (números) e
  **julgados por subagente** (estética/DFM, sem medir).

Mostre a spec e pergunte se pode modelar.

## Fase 3 — Modelagem

Comece de `templates/part.scad`. O `.scad` tem **apenas os inputs estritamente
necessários** no topo; tudo derivável é calculado (interno, parede mínima,
folgas já aplicadas, posições). Sem número mágico dentro de módulo.

```scad
w      = 40;    // inputs: literal único, com unidade no comentário
wall   = 3.2;
$fn = $preview ? 32 : 64;         // por peça; preview rápido, render fino

hole_x = w / 2;                   // derivados: nunca viram input
assert(wall >= 2 * nozzle, "parede fina demais");
echo(str("CHK|hole=", hole_d, "@0|wall=", wall));   // review.py lê isso
```

- `assert()` nos mínimos (parede ≥ 2 × bico, furo ≥ 2 × bico, folga ≥ 0).
- `echo(str("CHK|k=v|k=v"))` para todo valor derivado que a revisão precisa
  conferir — e todo furo como `CHK|hole=<d>@<z>`.
- Peça apoiada em **z=0**; uma peça por arquivo.
- Fillet/chamfer só com `hull()` ou `rotate_extrude()` — **nunca `minkowski()`**
  (lento e frágil).
- Sem `import()` de arquivo externo sem o usuário pedir.

## Fase 4 — Revisão (máx. 3 iterações)

```bash
./scripts/oscad.sh -o out/p.stl peca.scad            # só para olhar rápido
python3 scripts/review.py peca.scad --bbox X Y Z --volume V --nozzle 0.4
```

`review.py` exporta o STL, confere **gates** (erro/assert do OpenSCAD, malha
watertight, 1 sólido, volume > 0, bbox ±0.1 mm, volume ±1 %, base plana em z=0
(≥ 20 mm² e ≥ 90 % da área voltada p/ baixo num único plano — pegada vazada passa),
inputs mínimos) e **avisos** (overhang abaixo de 45°, furo < 2 × bico). Exit ≠ 0
se algum gate falhar. A espessura de parede **não** é medida por ele (exigiria raycast confiável); isso fica no `assert()` do `.scad` e no olho do subagente. Ele também gera PNGs em `out/` — se o OpenSCAD do host não
tiver OpenGL, isso sai como WARN e a revisão segue sem imagem.

Depois dos gates, o julgamento estético/DFM é de outro: subagente
`devils-advocate`, `async: true`, olhando os PNGs de `out/` + a spec. Ele **não
mede nada** (medição é do `review.py`) — só responde: parece imprimível? a
parede parece fina? o encaixe parece ter folga? o que mais chama atenção?

```
subagent({ agent: "devils-advocate", async: true, task: "Leia os PNGs em
  <dir>/out/ e a spec em <spec>. Não meça nada. Julgue como quem vai imprimir:
  DFM (parede, overhang, furo, cantos), estética e fit à função. Aponte o maior
  problema e diga se entrega." })
```

A cada iteração: grave `rev` (A, B, C) e **uma linha** no log da `spec.md`:

```
rev B — review.py: 0 FAIL, 1 WARN (overhang 12 mm² desde z=8). Subagente:
"canto vivo no topo". → arredondado o topo (hull).
```

Corrija o problema de maior peso, rode de novo. Três iterações sem passar:
entregue a melhor versão e diga o que ficou.

## Entrega

Diga o caminho do `.scad`, da `spec.md` e do STL em `out/`, o resultado do
`review.py` em uma linha e o que ficou pendente (suportes, cupom de teste,
parâmetro assumido). Sem CHANGELOG, sem tag, sem commit — release é do
`release.py`.

## Requisitos

OpenSCAD instalado (o `oscad.sh` procura no PATH, depois flatpak, depois um
distrobox `sbx-*`; **nunca instala nada**). Python 3 stdlib só. O flatpak
enxerga apenas `$HOME` — mantenha o projeto dentro dele.
