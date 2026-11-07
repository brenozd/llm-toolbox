# Spec — <nome da peça>

`rev: A` · unidade: **mm** · alvo: **FDM**

## Função

<uma frase: o que a peça faz e onde é usada>

## Parâmetros

| Nome | Valor | Origem | Nota |
| --- | --- | --- | --- |
| `w` | 40 | medido | paquímetro, borda a borda |
| `d` | 25 | medido | — |
| `h` | 30 | assumido | cabe no slot; confirmar com o usuário |
| `wall` | 3.2 | escolhido | ≥ 2 × bico |
| `hole_d` | 4.2 | escolhido | parafuso M4 + 0.2 de folga |

Origem é sempre **medido** (com o instrumento) ou **assumido** (e então o risco
está escrito na nota). Nada de número sem origem.

## Interfaces

| Onde | Encaixa com | Folga aplicada | Tipo |
| --- | --- | --- | --- |
| furo Ø[`hole_d`] | parafuso M4 | +0.2 no Ø | deslizante |

Folgas FDM de partida: 0.1 aperto · 0.15–0.25 deslizante · 0.3 folgado ·
furo encolhe 0.2–0.4 no Ø. Se a peça tem encaixe crítico, o entregável inclui
um cupom de teste com as 3 folgas.

## Impressão

- Bico: 0.4 mm · material: PLA
- Orientação: base no plano z=0, <por quê>
- Suportes: <nenhum / onde>

## Critérios de aceite

Verificados por `review.py` (gate objetivo):

- bbox = `<x> × <y> × <z>` mm, tolerância ±0.1 mm
- volume = `<v>` mm³, tolerância ±1 %
- malha watertight, 1 sólido, normais para fora
- base plana em z=0: zmin ≈ 0, ≥ 20 mm² de apoio e ≥ 90 % de toda a área
  voltada para baixo (nz < −0.99) no mesmo plano — pegada vazada passa,
  fundo em degraus não
- `assert()` nos mínimos: parede ≥ 2 × bico, furo ≥ 2 × bico

Julgados por subagente (estética/DFM, sem medir):

- <ex.: a parede não parece fina demais para o uso>
- <ex.: o furo tem material suficiente em volta>
- <ex.: nenhuma aresta viva onde a mão encosta>

## Log de revisão

`rev: A` — review.py: 0 FAIL, 2 WARN (overhang 12 mm² desde z=8). Subagente:
"parede OK, canto vivo no topo". → arredondado o topo.
