# storyboard-video: fases, dependências e spec (genérico)

Regra transversal: nenhum nome de projeto no schema, no SKILL ou nos lints. Exemplos só com `<placeholders>`. Lints derivam de `role`/`type`/`kind`, nunca de conteúdo.
Baseline: `cd servers/storyboard-video && python -m pytest -q tests/` (venv com mcp 1.30, pytest, jsonschema).

## Fatos verificados
- FastMCP 1.30 ignora kwargs desconhecidos (`render(profile=..)` chegou ao corpo). Rejeitar exige checagem própria no servidor.
- `duration_s` default 3.0 (`spec.py` normalize); lint 1.5..12 (`spec.py:736`). `timeline()` já estica a cena ao áudio + AUDIO_TAIL (`spec.py:~170`), então `"auto"` = usar `duration_s` só como mínimo.
- Cache TTS por texto+voz+lang+model_id (`tts.py:66`), arquivo `<scene>-<key>.wav` em `audio/<spec_hash>/`: um spec_hash novo cria dir novo e re-sintetiza (hipótese P5 confirmada em leitura: `p.exists()` checa só o dir do hash atual). Correção: procurar o WAV com a mesma key em `audio/*/`.
- `capture.json` já registra kwargs da captura (`capture.py:36`); `recipe` = estender isso, não criar formato novo.

## Fases

| Fase | Entrega | Arquivos | Depende de |
|---|---|---|---|
| F1 guard-rails | kwargs desconhecidos viram erro; `quality` obrigatório; lint `dense_capture` (chars/linha, nº de linhas, genérico) | server.py, spec.py, tests | — |
| F2 reuso de TTS | WAV com mesma key reaproveitado entre hashes (P5) | tts.py, tests/test_tts.py | — |
| F3 duração auto | `duration_s: "auto"` aceito; normalize mapeia para mínimo 1.5 e o timeline estica ao áudio; sem áudio, estima por palavras/`speak_wps` | spec.py, tests | — |
| F4 schema | `spec.schema.json` gerado de um dict único em `spec_schema.py`; tool `get_spec_schema`; `validate_spec` retorna `path` (JSON Pointer) nos findings | spec.py, spec_schema.py, server.py | F3 (tipo de duration_s) |
| F5 patch_spec | ops `replace/add/remove/move` por id de cena, `dry_run`, diff, novos lints, hash | patch.py, server.py | F4 (paths) |
| F6 intent/proveniência | `scene.intent {sees, understands}` opcional; `direction.strict_intent`; `capture.json` ganha `recipe` (cmd/script copiado) ; SKILL: blind read | spec.py, capture.py, SKILL.md | F4 |
| F7 SKILL/docs | seção Spec encurtada apontando ao schema; placeholders no lugar de `mint_loader`/`LD_PRELOAD`; protocolo de medição genérico (janela, ≥3 repetições, faixa) ; teste que barra nomes de projeto | SKILL.md, test_skill_docs.py | F1-F6 |
| Adiado | 4K, `clean_work`, UID do host, `brand_tokens(source)`, `scene.claims[]`, mover `direction.scenes`→cena, `migrate_spec` | — | sob demanda |

Cortado do v2 proposto (YAGNI): `constraints` como dado, `claims[]` com `kind`, `spec_version`/`migrate_spec`, objetos `timing`/`narration`. Mantém-se o formato plano atual, só aditivo: spec v1 continua válida sem migração.

## Spec (aditiva, genérica)
```jsonc
{ "scenes": [ {
    "id": "<string único>", "type": "title|bullets|terminal|image|code",
    "duration_s": "auto | <number 1.5..12>",
    "intent": { "sees": "<string>", "understands": "<string>" },   // opcional; obrigatório se direction.strict_intent
    "evidence": "<file:line | file:a-b>"                            // existente
} ] }
```
Finding: `{severity, code, scene, path, message, fix}` (`path` novo, JSON Pointer).
patch_spec: `{spec_hash, dry_run, ops:[{op, scene, path, value}]}` → `{ok, diff[], derived{}, findings[], spec_hash}`.

## Riscos
- Rejeitar kwargs pode quebrar clientes que mandam extras: erro lista argumentos válidos.
- `"auto"` muda tipo de `duration_s`: todo leitor de `sc["duration_s"]` precisa passar por normalize (grep de callers na F3).
- Reuso de WAV entre hashes: key inclui model_id, então troca de engine invalida.
