#!/usr/bin/env python3
"""Revisão automática de uma peça OpenSCAD para impressão FDM.

Exporta o STL via scripts/oscad.sh, checa a malha, compara com a spec e
gera PNGs de referência em out/ ao lado do .scad. Só stdlib.

Uso:
  review.py peca.scad [--bbox 40 25 30] [--volume 12345] [--nozzle 0.4]
  review.py --selftest      # fixtures em Python puro, sem OpenSCAD

Códigos de saída: 0 = nenhum FAIL, 1 = algum FAIL, 2 = uso inválido.
"""

import argparse
import json
import math
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OSCAD = HERE / "oscad.sh"
R = 6  # casas decimais usadas ao casar vértices (1e-6)
BASE_MIN_MM2 = 20.0  # área mínima de apoio real na mesa
BASE_COVER = 0.9     # fração da área voltada p/ baixo que o fundo deve cobrir


# ---------------------------------------------------------------- STL

def key(p):
    return (round(p[0], R), round(p[1], R), round(p[2], R))


def read_stl(path):
    """Aceita STL binário e ASCII. Retorna (triângulos, formato)."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if n > 0 and len(data) == 84 + 50 * n:
            tris = []
            for i in range(n):
                f = struct.unpack("<12fH", data[84 + 50 * i:134 + 50 * i])
                tris.append(((f[3], f[4], f[5]), (f[6], f[7], f[8]), (f[9], f[10], f[11])))
            return tris, "binary"
    nums = [float(x) for x in
            re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data.decode("utf-8", "replace"))
            for x in x]
    tris = [tuple(tuple(nums[i + j:i + j + 3]) for j in (0, 3, 6))
            for i in range(0, len(nums) - 8, 9)]
    return tris, "ascii"


def write_stl(tris, path, binary=False):
    if not binary:
        body = ["solid fixture"]
        for t in tris:
            body.append(" facet normal 0 0 0\n  outer loop")
            body += [f"   vertex {v[0]} {v[1]} {v[2]}" for v in t]
            body.append("  endloop\n endfacet")
        body.append("endsolid fixture\n")
        Path(path).write_text("\n".join(body))
        return
    out = bytearray(b"fixture" + b" " * 73)
    out += struct.pack("<I", len(tris))
    for t in tris:
        out += struct.pack("<3f", 0, 0, 0)
        for v in t:
            out += struct.pack("<3f", *v)
        out += struct.pack("<H", 0)
    Path(path).write_bytes(bytes(out))


def analyze(tris):
    """Métricas da malha: bbox, volume, watertight, shells, base, overhang."""
    if not tris:
        return {"empty": True}
    pts = [p for t in tris for p in t]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    size = [hi[i] - lo[i] for i in range(3)]

    vol = 0.0
    for a, b, c in tris:
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0

    edges = {}
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for t in tris:
        ks = [key(p) for p in t]
        for k in ks:
            parent.setdefault(k, k)
        for k1, k2 in ((ks[0], ks[1]), (ks[1], ks[2]), (ks[2], ks[0])):
            e = (k1, k2) if k1 <= k2 else (k2, k1)
            edges.setdefault(e, []).append((k1, k2))
            ra, rb = find(k1), find(k2)
            if ra != rb:
                parent[ra] = rb

    bad = sum(1 for v in edges.values() if len(v) != 2 or v[0] != v[1][::-1])
    shells = len({find(k) for k in parent})

    zmin = lo[2]
    base_area = down_area = over_area = 0.0
    over_z = None
    for a, b, c in tris:
        u = [b[i] - a[i] for i in range(3)]
        w = [c[i] - a[i] for i in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
        area = ln / 2.0
        nz = n[2] / ln
        at_bottom = all(abs(p[2] - zmin) < 1e-4 for p in (a, b, c))
        if nz < -0.99:
            down_area += area
            if at_bottom:
                base_area += area
                continue
        if nz < -0.7071:
            over_area += area
            z = min(a[2], b[2], c[2])
            over_z = z if over_z is None else min(over_z, z)

    return {"empty": False, "size": size, "min": lo, "max": hi, "volume": vol,
            "bad_edges": bad, "edges": len(edges), "shells": shells,
            "base_area": base_area, "down_area": down_area,
            "overhang_area": over_area, "overhang_z": over_z}


def base_flat(m):
    """Fundo apoiado num único plano em z=0, com área real (não depende da bbox)."""
    down = m["down_area"]
    return (abs(m["min"][2]) < 1e-4 and m["base_area"] >= BASE_MIN_MM2
            and m["base_area"] >= BASE_COVER * down)


# ---------------------------------------------------------------- openscad

def run_oscad(scad, outdir):
    stem = scad.stem
    stl, echo = outdir / f"{stem}.stl", outdir / f"{stem}.echo"
    for f in (stl, echo):
        f.unlink(missing_ok=True)
    cmd = [str(OSCAD), "-o", str(stl), "-o", str(echo), str(scad)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return p, stl, echo


def render_pngs(scad, outdir):
    """3 vistas best-effort; OpenSCAD sem OpenGL (flatpak headless) falha aqui."""
    views = {"iso": "55,0,25", "front": "90,0,0", "top": "0,0,0"}
    made, err = [], ""
    for name, rot in views.items():
        png = outdir / f"{scad.stem}_{name}.png"
        png.unlink(missing_ok=True)
        p = subprocess.run([str(OSCAD), "-o", str(png), "--imgsize=900,700",
                            "--projection=o", f"--camera=0,0,0,{rot},0",
                            "--autocenter", "--viewall", "--render=true", str(scad)],
                           capture_output=True, text=True, timeout=600)
        if png.exists() and png.stat().st_size > 0:
            made.append(png)
        else:
            png.unlink(missing_ok=True)
            out = [ln.strip() for ln in (p.stderr or "").splitlines() if ln.strip()]
            err = next((ln for ln in out if "ERROR" in ln or "Assertion" in ln
                        or "OffscreenView" in ln), out[-1] if out else "sem saída")
    return made, err


def echo_values(text):
    """Valores de `echo(str("CHK|k=v|k=v"))`, preservando a ordem."""
    pairs = []
    for m in re.finditer(r'CHK\|([^"]*)', text):
        for chunk in m.group(1).split("|"):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                pairs.append((k.strip(), v.strip()))
    return pairs


# ---------------------------------------------------------------- lint

TRIVIAL = {"0", "1", "2", "0.5", "32", "64", "-1", "-0"}
INPUT = re.compile(r"^[A-Za-z_][\w$]*\s*=\s*-?\d+\.?\d*\s*;\s*$")
DEF = re.compile(r"^\s*(module|function)\s+[\w$]+\s*\(")
LIT = re.compile(r"(?<![\w$.])-?\d+\.?\d*")


def lint(scad_text):
    """Inputs no topo e literais soltos dentro de module/function.

    Fora de module/function nada é literal solto: assert()/echo() de topo e
    fórmulas de variáveis derivadas são legítimos.
    """
    lines = [ln.split("//")[0] for ln in scad_text.splitlines()]
    inputs, bad, depth, in_def = [], [], 0, False
    for i, ln in enumerate(lines, 1):
        opens = DEF.match(ln) is not None
        # input = atribuição de um único literal no topo; o resto é derivado
        if not in_def and depth == 0 and INPUT.match(ln):
            inputs.append(ln.split("=", 1)[0].strip())
        if in_def or opens:
            bad += [(i, lit) for lit in LIT.findall(ln) if lit not in TRIVIAL]
        depth += ln.count("{") - ln.count("}")
        if opens:
            in_def = True
        if in_def and depth <= 0:
            in_def = False
    return inputs, bad


# ---------------------------------------------------------------- relatório

class Report:
    def __init__(self):
        self.rows = []

    def add(self, status, name, detail=""):
        self.rows.append((status, name, detail))

    def fails(self):
        return [r for r in self.rows if r[0] == "FAIL"]

    def dump(self):
        w = max([len(n) for _, n, _ in self.rows] + [6])
        for s, n, d in self.rows:
            print(f"{s:4}  {n:<{w}}  {d}")
        print(f"\n{len(self.rows)} checagens: "
              f"{sum(r[0] == 'PASS' for r in self.rows)} PASS, "
              f"{sum(r[0] == 'WARN' for r in self.rows)} WARN, "
              f"{sum(r[0] == 'FAIL' for r in self.rows)} FAIL")


def review(scad, args):
    rep = Report()
    outdir = Path(args.out) if args.out else scad.parent / "out"

    if not scad.exists():
        rep.add("FAIL", "arquivo", f"{scad} não existe")
        return rep
    outdir.mkdir(parents=True, exist_ok=True)
    if not OSCAD.exists():
        rep.add("FAIL", "oscad.sh", f"não encontrado em {OSCAD}")
        return rep

    p, stl, echofile = run_oscad(scad, outdir)
    stderr = p.stderr or ""
    lines = stderr.splitlines()
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    warns = [ln for ln in lines if ln.startswith("WARNING:")]
    if errors:
        rep.add("FAIL", "openscad", errors[0][:110])
    elif not stl.exists() or stl.stat().st_size < 84:
        rep.add("FAIL", "openscad", "sem STL exportado (veja a saída do openscad)")
    else:
        rep.add("PASS", "openscad", "exportou STL sem ERROR")
    if warns:
        rep.add("WARN", "openscad-warnings", f"{len(warns)}x: {warns[0][:90]}")
    if "Current top level object is empty" in stderr:
        rep.add("FAIL", "geometria", "objeto vazio em z (nada a exportar)")
        return rep
    if not stl.exists() or stl.stat().st_size < 84:
        return rep

    tris, fmt = read_stl(stl)
    m = analyze(tris)
    rep.add("PASS", "malha", f"{len(tris)} triângulos, STL {fmt}")

    if m.get("empty"):
        rep.add("FAIL", "malha", "STL sem triângulos")
        return rep

    rep.add("PASS" if m["bad_edges"] == 0 else "FAIL", "watertight",
            "todas as arestas em pares opostos" if m["bad_edges"] == 0
            else f"{m['bad_edges']}/{m['edges']} arestas quebradas")

    rep.add("PASS" if m["shells"] == 1 else "FAIL", "shells",
            f"{m['shells']} corpo(s) sólido(s)" + ("" if m["shells"] == 1 else " — esperado 1"))

    rep.add("PASS" if m["volume"] > 0 else "FAIL", "volume>0",
            f"{m['volume']:.2f} mm³" + ("" if m["volume"] > 0 else " — normais invertidas"))

    sx, sy, sz = m["size"]
    rep.add("PASS", "bbox", f"{sx:.2f} x {sy:.2f} x {sz:.2f} mm")
    if args.bbox:
        want = args.bbox
        diffs = [abs(m["size"][i] - want[i]) for i in range(3)]
        ok = max(diffs) <= args.bbox_tol
        rep.add("PASS" if ok else "FAIL", "bbox vs spec",
                f"{sx:.2f}x{sy:.2f}x{sz:.2f} vs {want[0]}x{want[1]}x{want[2]} "
                f"(tol ±{args.bbox_tol} mm, pior Δ={max(diffs):.3f})")

    if args.volume:
        dev = abs(m["volume"] - args.volume) / args.volume
        ok = dev <= args.vol_tol
        rep.add("PASS" if ok else "FAIL", "volume vs spec",
                f"{m['volume']:.1f} vs {args.volume:.1f} mm³ (Δ{dev * 100:.2f}%, "
                f"tol ±{args.vol_tol * 100:.0f}%)")

    cover = m["base_area"] / (m["down_area"] or 1)
    rep.add("PASS" if base_flat(m) else "FAIL", "base plana",
            f"zmin={m['min'][2]:.4f} mm, fundo={m['base_area']:.1f} mm² "
            f"({cover * 100:.0f}% dos {m['down_area']:.1f} mm² voltados p/ baixo)")

    inputs, lits = lint(scad.read_text())
    rep.add("PASS", "inputs", f"{len(inputs)}: {', '.join(inputs) or '—'}")
    if lits:
        first = ", ".join(f"L{i}:{v}" for i, v in lits[:5])
        rep.add("WARN", "literais em módulos",
                f"{len(lits)} valor(es) fixo(s) fora do topo ({first})")

    if m["overhang_area"] > 0:
        rep.add("WARN", "overhang",
                f"{m['overhang_area']:.1f} mm² abaixo de 45° desde z={m['overhang_z']:.2f} mm")

    if echofile.exists():
        pairs = echo_values(echofile.read_text())
        if pairs:
            rep.add("INFO", "CHK", " ".join(f"{k}={v}" for k, v in pairs))
        for k, v in pairs:
            if k == "hole":
                d = float(v.split("@")[0])
                min_d = 2 * args.nozzle
                if d < min_d:
                    rep.add("WARN", "furo pequeno",
                            f"Ø{d:.2f} < Ø{min_d:.2f} (2*nozzle) — não imprime redondo")
    else:
        rep.add("WARN", "CHK", "nenhum valor echo CHK no .echo")

    if not args.no_png:
        made, err = render_pngs(scad, outdir)
        rep.add("PASS" if len(made) == 3 else "WARN", "pngs",
                f"{len(made)}/3 em {outdir}" if made else f"não renderizou ({err[:60]})")

    return rep


# ---------------------------------------------------------------- selftest

def cube_tris(size=10.0):
    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
         (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    v = [tuple(c * size for c in p) for p in v]
    faces = [(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return [tuple(v[i] for i in f) for f in faces]


def box_tris(lo, hi):
    """Caixa alinhada aos eixos como triângulos."""
    f = lambda p: tuple(lo[i] + p[i] * (hi[i] - lo[i]) for i in range(3))  # noqa: E731
    return [tuple(f(p) for p in t) for t in cube_tris(1.0)]


def frame_tris(size=40.0, band=4.0, h=3.0):
    """Moldura quadrada: fundo 100% plano mas vazado (36% da bbox)."""
    s, b = size, band
    return (box_tris((0, 0, 0), (s, b, h)) + box_tris((0, b, 0), (b, s - b, h))
            + box_tris((s - b, b, 0), (s, s - b, h)) + box_tris((0, s - b, 0), (s, s, h)))


def step_tris(size=40.0, raised=30.0):
    """Fundo em dois níveis: placa + bloco elevado."""
    return box_tris((0, 0, 0), (size, size, 2)) + box_tris((0, 0, 2), (raised, raised, 7))


def selftest():
    ok = True

    def check(cond, label):
        nonlocal ok
        print(f"{'PASS' if cond else 'FAIL'}  {label}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tris = cube_tris()
        write_stl(tris, tmp / "a.stl")
        write_stl(tris, tmp / "a.bin.stl", binary=True)

        for name in ("a.stl", "a.bin.stl"):
            t, fmt = read_stl(tmp / name)
            m = analyze(t)
            check(len(t) == 12 and m["bad_edges"] == 0 and m["shells"] == 1
                  and abs(m["volume"] - 1000) < 1e-3
                  and abs(m["base_area"] - 100) < 1e-6, f"cubo {fmt}: watertight, 1 shell, 1000 mm³, base 100 mm²")

        write_stl(tris[1:], tmp / "b.stl")  # falta um triângulo
        m = analyze(read_stl(tmp / "b.stl")[0])
        check(m["bad_edges"] > 0, f"triângulo removido detectado ({m['bad_edges']} arestas)")

        write_stl(tris + [tuple((p[0] + 20, p[1], p[2]) for p in t) for t in tris],
                  tmp / "c.stl")
        check(analyze(read_stl(tmp / "c.stl")[0])["shells"] == 2, "dois cubos: 2 shells")

        inside_out = [tuple(reversed(t)) for t in tris]
        check(analyze(inside_out)["volume"] < 0, "normais invertidas: volume negativo")

        pairs = echo_values('ECHO: "CHK|w=10|hole=4.2@0"')
        check(pairs == [("w", "10"), ("hole", "4.2@0")], "parser de CHK")

        ins, lits = lint("w = 10;\nd = 20;\nmodule p() {\n  cube([3, w, 7]);\n}\n")
        check(ins == ["w", "d"] and len(lits) == 2, f"lint: 2 inputs, {len(lits)} literais")

        flat = analyze(read_stl(tmp / "a.stl")[0])
        check(base_flat(flat), "cubo: base plana")
        write_stl(frame_tris(), tmp / "frame.stl")
        fr = analyze(read_stl(tmp / "frame.stl")[0])
        check(base_flat(fr) and fr["base_area"] < 0.5 * fr["size"][0] * fr["size"][1],
              f"fundo vazado plano passa ({fr['base_area']:.0f} mm² de "
              f"{fr['size'][0] * fr['size'][1]:.0f} mm² da bbox)")
        write_stl(step_tris(), tmp / "step.stl")
        st = analyze(read_stl(tmp / "step.stl")[0])
        check(not base_flat(st), f"fundo em 2 níveis falha ({st['base_area']:.0f}/{st['down_area']:.0f} mm²)")

    print("\nSELFTEST " + ("OK" if ok else "FALHOU"))
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(description="Revisão automática de peça OpenSCAD (FDM).")
    ap.add_argument("scad", nargs="?", help="arquivo .scad a revisar")
    ap.add_argument("--bbox", nargs=3, type=float, metavar=("X", "Y", "Z"),
                    help="bbox esperada da spec [mm]")
    ap.add_argument("--volume", type=float, help="volume esperado da spec [mm³]")
    ap.add_argument("--nozzle", type=float, default=0.4, help="Ø do bico [mm] (padrão 0.4)")
    ap.add_argument("--bbox-tol", type=float, default=0.1, help="tolerância bbox [mm]")
    ap.add_argument("--vol-tol", type=float, default=0.01, help="tolerância volume (fração)")
    ap.add_argument("--out", help="pasta de saída (padrão: out/ ao lado do .scad)")
    ap.add_argument("--no-png", action="store_true", help="não gerar PNGs")
    ap.add_argument("--selftest", action="store_true", help="fixtures em Python, sem OpenSCAD")
    ap.add_argument("--json", action="store_true", help="saída em JSON em vez de tabela")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.scad:
        ap.error("informe o .scad ou use --selftest")

    rep = review(Path(args.scad).resolve(), args)
    if args.json:
        print(json.dumps([{"status": s, "check": n, "detail": d} for s, n, d in rep.rows],
                         ensure_ascii=False, indent=2))
    else:
        rep.dump()
    return 1 if rep.fails() else 0


if __name__ == "__main__":
    sys.exit(main())
