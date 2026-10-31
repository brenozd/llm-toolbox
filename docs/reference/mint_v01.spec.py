CAP = {"leaky": "56f31dbf", "fixed": "a00fa7bd"}
def cap(k): return dict(video=f"/work/captures/{CAP[k]}/session.mp4", poster=f"/work/captures/{CAP[k]}/poster.png")
import json, subprocess
SAY = {"LD_PRELOAD": "L D preload", "OK": "ok", "mint_loader": "mint loader", "MIT": "mit", "memfd": "mem F D", "stderr": "standard error", "mint": "mint"}
def _code():
    from storyboard_video_mcp import server as s
    return s.extract_code.__wrapped__("src/loader/loader.c", "66-72") if hasattr(s.extract_code, "__wrapped__") else None
CODE = open("/repo/src/loader/loader.c").read().split("\n")
CODE = "\n".join(CODE[65:72])
SPEC = {"say": SAY,
 "fps": 30, "aspect": "16:9", "lang": "pt-BR",
 "direction": {"purpose": "feature-demo", "tone": "calm technical", "audio": "voice", "arc": "hero",
   "palette": {"bg": "#0f1115", "fg": "#f2f4f8", "accent": "#7ee787"}, "palette_source": "user",
   "brief": {"audience": "devs C/C++ em Linux", "pain": "vazamento de memória que passa em silêncio",
             "promise": "descobrir quantos bytes vazaram sem recompilar o programa", "cta": "compile com CMake e rode o mint_loader",
             "placement": "hero"},
   "scenes": {
     "hook": {"role": "hook", "narration": True}, "why": {"role": "problem", "narration": True},
     "leak": {"role": "reveal", "narration": True}, "how": {"role": "value", "narration": True},
     "feat": {"role": "value", "narration": True}, "ok": {"role": "result", "narration": True},
     "cta": {"role": "cta", "narration": True}}},
 "scenes": [
  {"id": "hook", "type": "title", "title": "Seu programa C vaza memória?", "subtitle": "mint: rastreador de leaks via LD_PRELOAD",
   "duration_s": 4, "narration": "Seu programa em C vaza memória, e ninguém avisa."},
  {"id": "why", "type": "bullets", "heading": "O problema", "evidence": "README.md:3",
   "items": ["Um malloc sem free passa em silêncio", "O programa roda normal", "O vazamento só aparece em produção"],
   "duration_s": 8, "narration": "Um malloc sem free passa em silêncio. O programa roda normal, e o vazamento só aparece em produção, quando já custa caro."},
  {"id": "leak", "type": "terminal", "heading": "mint_loader ./leaky", **cap("leaky"), "title": "terminal", "duration_s": 9.5,
   "narration": "O mint roda o seu programa do jeito que ele está, e ao sair diz quantos bytes vazaram. Aqui, cento e vinte e oito bytes, na hora, sem recompilar nada."},
  {"id": "how", "type": "code", "source": "src/loader/loader.c:66-72", "code": CODE, "duration_s": 9,
   "narration": "O loader grava a biblioteca num memfd, aponta o LD_PRELOAD para ele e executa o seu programa. Nenhum arquivo so fica no disco."},
  {"id": "feat", "type": "bullets", "heading": "O que ele intercepta", "evidence": "README.md:5",
   "items": ["malloc, calloc e realloc", "free e memalign", "Resumo no stderr ao sair"],
   "duration_s": 5, "narration": "Ele intercepta malloc, calloc, realloc, free e memalign, e imprime o resumo no stderr."},
  {"id": "ok", "type": "terminal", "heading": "Depois do free", **cap("fixed"), "title": "terminal", "duration_s": 9.5,
   "narration": "Adicione o free que faltava, e compile de novo, e o resumo vira OK: nenhum vazamento detectado. É o mesmo programa, só com uma linha a mais."},
  {"id": "cta", "type": "title", "title": "mint", "subtitle": "cmake -S . -B build · licença MIT", "duration_s": 3.5,
   "narration": "Compile com CMake e rode o mint_loader. Código aberto, licença MIT."},
 ]}
