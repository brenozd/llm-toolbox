from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from . import config
from .safety import SKIP_DIRS, denied, safe_path

MARKERS = {"package.json": "js", "pyproject.toml": "python", "setup.py": "python", "requirements.txt": "python",
           "Cargo.toml": "rust", "go.mod": "go", "CMakeLists.txt": "c/c++", "Makefile": "make", "meson.build": "c/c++",
           "pom.xml": "java", "build.gradle": "java", "pubspec.yaml": "dart"}
KIND_HINTS = {
    "web": r"\b(react|vue|svelte|next|nuxt|vite|angular|express|fastapi|flask|django|rails|actix-web|axum|gin|fiber|astro)\b|index\.html",
    "gui": r"\b(qt[56]?|pyqt\d?|pyside\d?|gtk[34]?|gtkmm|tkinter|electron|tauri|imgui|sdl[23]?|wxwidgets|flutter|egui|iced|slint|kivy|glfw)\b",
    "mcp": r"\b(mcp|model-context-protocol|fastmcp)\b",
    "cli": r"\b(argparse|click|typer|clap|cobra|getopt|commander|yargs|argc|cli)\b",
}
FENCE = re.compile(r"^```\s*(sh|bash|shell|console|zsh)\s*$")


def _walk(root: Path, cap: int):
    n = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            n += 1
            if n > cap:
                return
            yield Path(dp) / fn


def _readme(root: Path) -> dict:
    for name in ("README.md", "README.rst", "README", "readme.md"):
        p = root / name
        if p.exists():
            lines = p.read_text(errors="replace").splitlines()
            title = next(((i + 1, l.lstrip("# ").strip()) for i, l in enumerate(lines) if l.startswith("#")), (1, root.name))
            tag = next(((i + 1, l.strip()) for i, l in enumerate(lines) if i + 1 > title[0] and l.strip()
                        and not l.startswith(("#", "```", "[", "!", "|", "<"))), (0, ""))
            cmds, fenced = [], False
            for i, l in enumerate(lines):
                if FENCE.match(l.strip()):
                    fenced = True
                elif l.strip().startswith("```"):
                    fenced = False
                elif fenced and l.strip() and not l.lstrip().startswith("#"):
                    cmds.append({"cmd": l.strip().lstrip("$ "), "evidence": f"{name}:{i + 1}"})
            return {"file": name, "title": title[1], "title_line": title[0], "tagline": tag[1], "tagline_line": tag[0], "commands": cmds[:25]}
    return {"file": None, "title": root.name, "tagline": "", "commands": []}


def scan_repo(repo: str | None = None, max_files: int = 6000) -> dict:
    root = safe_path(repo or config.REPO)
    stacks, skipped, haystack, entry, logos, env_names = set(), [], [], [], [], []
    for p in _walk(root, max_files):
        rel = p.relative_to(root)
        if denied(p):
            skipped.append(str(rel))
            continue
        if p.name in MARKERS and len(rel.parts) <= 2:
            stacks.add(MARKERS[p.name])
            if p.stat().st_size < 200_000:
                haystack.append(p.read_text(errors="replace").lower())
        if p.suffix in (".html", ".qml", ".ui", ".glade", ".xaml"):
            haystack.append(p.suffix + " " + p.name.lower())
        if p.name in (".env.example", ".env.sample"):  # names only, never values
            env_names += [l.split("=")[0].strip() for l in p.read_text(errors="replace").splitlines() if "=" in l and not l.startswith("#")]
        if re.match(r"(main|app|cli|index|server)\.\w+$", p.name) and len(rel.parts) <= 3:
            entry.append(str(rel))
        if re.match(r"(logo|icon).*\.(svg|png)$", p.name, re.I) and len(logos) < 5:
            logos.append(str(rel))
    text = " ".join(haystack)
    scores = {k: len(re.findall(rx, text)) for k, rx in KIND_HINTS.items()}
    rd = _readme(root)
    scores["cli"] += len(rd["commands"]) // 3  # README full of shell lines => something runnable
    kinds = [k for k, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0]
    return {"status": "ok", "repo": str(root), "name": rd["title"], "stacks": sorted(stacks), "kind_scores": scores,
            "kind_guess": kinds[0] if kinds else "lib", "kinds": kinds[:3], "readme": rd, "entrypoints": entry[:10],
            "logos": logos, "env_var_names": env_names[:20], "forbidden_skipped": skipped[:20],
            "note": "kind_guess is a heuristic; confirm with the user. Capture: web->capture_web, cli->capture_terminal, gui->capture_gui"}


HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
FONT = re.compile(r"font-family\s*:\s*([^;}{]+)")


def _lum(hx: str) -> float:
    hx = hx.lstrip("#")
    hx = "".join(c * 2 for c in hx) if len(hx) == 3 else hx
    c = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two hex colours (used by brand_tokens and by the direction palette lint)."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def brand_tokens(repo: str | None = None) -> dict:
    root = safe_path(repo or config.REPO)
    colors, fonts, srcs = Counter(), Counter(), []
    for p in _walk(root, 4000):
        if denied(p) or p.suffix not in (".css", ".scss", ".qss", ".less") and "tailwind.config" not in p.name:
            continue
        if p.stat().st_size > 300_000:
            continue
        t = p.read_text(errors="replace")
        colors.update(c.lower() for c in HEX.findall(t))
        for f in FONT.findall(t):
            fonts[f.split(",")[0].strip(" '\"")] += 1
        srcs.append(str(p.relative_to(root)))
    top = [c for c, _ in colors.most_common(8)]
    # darkest as bg, lightest as fg, most vivid remaining as accent; else defaults tagged guess
    if len(top) >= 2:
        bg, fg = min(top, key=_lum), max(top, key=_lum)
        rest = [c for c in top if c not in (bg, fg)]
        acc = rest[0] if rest else None
        prov = "found"
    else:
        bg = fg = acc = None
        prov = "guess"
    theme = {"bg": bg or "#0f1115", "fg": fg or "#f2f4f8", "accent": acc or "#4cc2ff"}
    fixed = False
    if contrast(theme["bg"], theme["fg"]) < 4.5:
        theme["fg"], fixed = ("#ffffff" if _lum(theme["bg"]) < 0.5 else "#000000"), True
    if contrast(theme["bg"], theme["accent"]) < 3:
        theme["accent"], fixed = ("#4cc2ff" if _lum(theme["bg"]) < 0.5 else "#0b6bcb"), True
    return {"status": "ok", "theme": theme, "provenance": prov, "contrast_autofixed": fixed,
            "palette": top, "fonts": [f for f, _ in fonts.most_common(3)], "sources": srcs[:10]}


def extract_code(repo: str | None, path: str, lines: str) -> dict:
    root = safe_path(repo or config.REPO)
    p = safe_path(root / path, [root])
    a, _, b = lines.partition("-")
    a, b = int(a), int(b or a)
    if b - a + 1 > 18 or a < 1:
        return {"status": "error", "message": "range must be 1..18 lines starting at >=1"}
    src = p.read_text(errors="replace").splitlines()[a - 1:b]
    return {"status": "ok", "code": "\n".join(src), "source": f"{path}:{a}-{b}" if b != a else f"{path}:{a}"}
