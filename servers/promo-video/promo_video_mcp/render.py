from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import statistics
import subprocess
import threading
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import audio as A, config, layout, spec as S
from .safety import safe_path

ARGS = ["--disable-gpu", "--disable-dev-shm-usage", "--disable-lcd-text", "--font-render-hinting=none",
        "--force-color-profile=srgb", "--hide-scrollbars", "--no-sandbox"]
E = html.escape

CSS = """
*{box-sizing:border-box;margin:0}html,body{width:100%;height:100%;overflow:hidden;background:var(--bg)}
body{font-family:'Inter','DejaVu Sans','Liberation Sans',sans-serif;color:var(--fg)}
.scene{position:absolute;inset:0;display:none}
.c{position:absolute;top:var(--pad-top);left:var(--pad-x);right:var(--pad-x);bottom:var(--pad-bottom);padding:calc(var(--u)*1.2);display:flex;flex-direction:column;justify-content:center;gap:calc(var(--u)*3)}
.center{align-items:center;text-align:center}
h1{font-size:calc(var(--u)*9);line-height:1.1;font-weight:800}
h2{font-size:calc(var(--u)*6);color:var(--accent);font-weight:700}
.sub{font-size:calc(var(--u)*3.6);color:var(--muted)}
ul{list-style:none;display:flex;flex-direction:column;gap:calc(var(--u)*2.4)}
li{font-size:calc(var(--u)*4);padding-left:calc(var(--u)*4);position:relative}
li:before{content:'';position:absolute;left:0;top:.55em;width:calc(var(--u)*1.4);height:calc(var(--u)*1.4);border-radius:50%;background:var(--accent)}
pre,.term{font-family:'DejaVu Sans Mono','Liberation Mono',monospace;font-size:calc(var(--u)*2.5);line-height:1.45;background:var(--panel);border:2px solid var(--line);border-radius:calc(var(--u)*1.5);padding:calc(var(--u)*3);white-space:pre-wrap;word-break:break-all;overflow:hidden}
.term .l{display:block;min-height:1.45em}.term .p{color:var(--accent)}
.frame{flex:1;min-height:0;overflow:hidden;position:relative;border-radius:calc(var(--u)*1.5);border:2px solid var(--line);background:var(--panel)}
.frame img{width:100%;height:100%;object-fit:contain;display:block}
.frame img[data-z]{position:absolute;object-fit:fill;max-width:none;max-height:none}
.win{display:flex;flex-direction:column;align-self:center;max-width:100%;max-height:100%;min-height:0;border-radius:calc(var(--u)*1.2);border:2px solid var(--line);background:var(--panel);overflow:hidden}
.tbar{display:flex;align-items:center;gap:calc(var(--u)*.9);padding:calc(var(--u)*1) calc(var(--u)*1.5);background:var(--panel);border-bottom:1px solid var(--line)}
.tbar i{width:calc(var(--u)*1.3);height:calc(var(--u)*1.3);border-radius:50%;background:var(--line);display:block}
.tbar i:nth-child(1){background:#ff5f57}.tbar i:nth-child(2){background:#febc2e}.tbar i:nth-child(3){background:#28c840}
.tbar span{font-family:'DejaVu Sans Mono',monospace;font-size:calc(var(--u)*2);color:var(--muted);margin-left:calc(var(--u)*1.2)}
.wbody{flex:1;min-height:0;display:flex;align-items:center;justify-content:flex-start;overflow:hidden;background:var(--panel)}
.wbody img{max-width:100%;max-height:100%;display:block}
.src{font-family:'DejaVu Sans Mono',monospace;font-size:calc(var(--u)*2.2);color:var(--muted)}
.cap{position:absolute;left:var(--pad-x);right:var(--pad-x);bottom:var(--cap-bottom);text-align:center;font-size:calc(var(--u)*3);background:rgba(0,0,0,.6);padding:calc(var(--u)*1.2) calc(var(--u)*2.4);border-radius:calc(var(--u)*1);width:fit-content;margin:auto}
"""

JS = """
const T=%(trans)d,SC=%(scenes)s,M=%(motion)s,F=%(fps)d;
const cl=x=>Math.max(0,Math.min(1,x)),ease=p=>1-Math.pow(1-p,3);
const SET=Math.max(1,Math.round(F*0.8));   /* settle time in frames, from the fps: 0.8 s at any frame rate */
const els=[...document.querySelectorAll('.scene')];
function seek(f){
 els.forEach((el,i)=>{
  const s=SC[i],l=f-s.start;
  if(l<0||l>=s.dur){el.style.display='none';return}
  el.style.display='block';
  /* Overlap-free crossfade: the outgoing scene is gone before the incoming one starts, so the
     previous scene's text can never show through the next one mid-transition (a plain crossfade
     left the old terminal bleeding behind the new scene's transparent background). */
  let o=1, h=T/2;
  if(T){ if(i>0)o=Math.min(o,cl((l-h)/h)); if(i<SC.length-1)o=Math.min(o,cl((s.dur-h-l)/h)); }
  el.style.opacity=o;
  /* M: still = the frame never moves; subtle = it settles in the first 0.8 s and then holds (the fix
     for "the text keeps growing"); lively = the old linear zoom over the whole scene. */
  const c=el.querySelector('.c');
  if(c)c.style.transform=M==='still'?'':(M==='lively'?'scale('+(1+0.02*l/s.dur)+')':
    'scale('+(0.98+0.02*ease(cl(l/SET)))+')');
  el.querySelectorAll('.rv').forEach(r=>{const p=ease(cl((l-(+r.dataset.d))/12));r.style.opacity=p;r.style.transform='translateY('+((1-p)*24)+'px)'});
  el.querySelectorAll('.step').forEach(r=>{r.style.visibility=l>=(+r.dataset.d)?'visible':'hidden'});
  const vb=el.querySelector('[data-vmap]');
  if(vb){const m=JSON.parse(vb.dataset.vmap),fr=vb.querySelectorAll('img'),k=m[Math.max(0,Math.min(m.length-1,Math.floor(l)))];fr.forEach((x,j)=>{x.style.display=j===k?'block':'none'})}
  const q=(window.__ZOOM||{})[el.id];
  if(q){const zz=M==='still'?q.z:1+(q.z-1)*ease(cl(l/(s.dur*(M==='lively'?0.7:0.25))));   /* origin sits on the pivot, so it holds still while z grows */
   el.querySelectorAll('img[data-z]').forEach(im=>{im.style.transform='translate('+(-q.ox)+'px,'+(-q.oy)+'px) scale('+zz+')'})}
 });
}
"""


def _mix(a: str, b: str, t: float) -> str:
    """Hex blend of two #rrggbb colours (t=0 -> a): the window/terminal chrome is derived from the theme,
    so a light user palette gets a visible border instead of white-on-white panels."""
    ca, cb = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _img_uri(path: str) -> str:
    p = safe_path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def clip_frames(video: str, n: int, fps: float) -> list[str]:
    """Decompose a clip into at most n PNG frames at its own fps. Cached on disk, so a re-render
    seeks the same images (a <video> seek would not be deterministic frame for frame)."""
    p = safe_path(video)
    st = p.stat()
    key = hashlib.sha256(f"{config.RENDER_VERSION}|{p}|{st.st_size}|{st.st_mtime_ns}|{n}|{fps}".encode()).hexdigest()[:12]
    d = config.WORK / "frames" / key
    have = sorted(d.glob("*.png")) if d.is_dir() else []
    if len(have) < n:
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.png"):
            old.unlink()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", f"fps={fps},scale='min(iw,1920)':-2",
                        "-frames:v", str(n), str(d / "%04d.png")], check=True)
        have = sorted(d.glob("*.png"))
    return [str(x) for x in have[:n]]


def _vmap(n: int, dur: int, clip_fps: float, fps: int) -> list[int]:
    """Scene frame -> clip frame: plays the clip at its own speed and freezes the last frame."""
    return [min(n - 1, int(f * clip_fps / fps)) for f in range(dur)] if n else []


def _box_scale(w: int, h: int, aspect: str, heading: bool, iw: int, ih: int) -> float:
    """How much a capture can grow inside the scene's content box: as large as the box allows while
    keeping its aspect ratio (a recording shown at its own 1056x634 would stay a stamp of 16 px text)."""
    lay = layout.layout(aspect)
    u = min(w, h) / 100.0
    avail_w = w * (1 - 2 * lay["pad_x"]) - 2 * 1.2 * u
    avail_h = h * (1 - lay["pad_top"] - lay["pad_bottom"]) - 2 * 1.2 * u
    avail_h -= (6 * u * 1.25 + 3 * u) if heading else 0  # h2 + the .c gap
    avail_h -= 1.3 * u + 2 * 1.0 * u + 4  # title bar + its padding + the window border
    if iw <= 0 or ih <= 0 or avail_w <= 0 or avail_h <= 0:
        return 1.0
    return max(0.2, min(3.0, min(avail_w / iw, avail_h / ih)))


def _cls(sc: dict) -> str:
    """The content box: `center` when the direction aligns this scene centred, else the grid's left edge."""
    return 'class="c center"' if sc.get("align") == "center" else 'class="c"'


def _clip(sc: dict, dur: int) -> tuple[dict, list[str]]:
    """Probe a scene's clip (mp4, webm or gif) and decompose it into at most one still per scene frame."""
    pr = _probe(str(safe_path(sc["video"])))
    n = max(1, min(dur, round(pr["duration"] * pr["fps"])))
    try:
        frames = clip_frames(sc["video"], n, pr["fps"])
    except (subprocess.CalledProcessError, OSError):
        frames = []
    if not frames and sc.get("poster"):
        frames = [str(safe_path(sc["poster"]))]
    if not frames:
        raise RuntimeError(f"could not read frames from {sc['video']}")
    return pr, frames


def _terminal_video(sc: dict, fps: int, dur: int, w: int = 1920, h: int = 1080, aspect: str = "16:9") -> str:
    """A real session recording, one still per scene frame, inside a fake window title bar."""
    pr, frames = _clip(sc, dur)
    s = _box_scale(w, h, aspect, bool(sc.get("heading")), pr["width"], pr["height"])
    size = f"width:{round(pr['width'] * s)}px;height:{round(pr['height'] * s)}px"
    imgs = "".join(f'<img src="{_img_uri(p)}" style="display:{"block" if i == 0 else "none"};{size}">'
                   for i, p in enumerate(frames))
    vm = E(json.dumps(_vmap(len(frames), dur, pr["fps"], fps)))
    head = f'<h2 class="rv" data-d="0">{E(sc["heading"])}</h2>' if sc.get("heading") else ""
    title = E(sc.get("title") or "terminal")
    return (f'<div {_cls(sc)}>{head}<div class="win"><div class="tbar"><i></i><i></i><i></i><span>{title}</span></div>'
            f'<div class="wbody" data-vmap="{vm}">{imgs}</div></div></div>')


def _scene(sc: dict, fps: int, dur: int, w: int = 1920, h: int = 1080, aspect: str = "16:9") -> str:
    ty, body = sc["type"], ""
    if ty == "title":
        body = f'<div {_cls(sc)}><h1 class="rv" data-d="0">{E(sc["title"])}</h1><p class="sub rv" data-d="8">{E(sc.get("subtitle", ""))}</p></div>'
    elif ty == "bullets":
        lis = "".join(f'<li class="rv" data-d="{8 + i * 10}">{E(x)}</li>' for i, x in enumerate(sc["items"]))
        body = f'<div {_cls(sc)}><h2 class="rv" data-d="0">{E(sc["heading"])}</h2><ul>{lis}</ul></div>'
    elif ty == "terminal":
        if sc.get("video"):
            body = _terminal_video(sc, fps, dur, w, h, aspect)
        else:
            lines = sc.get("lines") or json.loads((config.WORK / "captures" / sc["capture_id"] / "lines.json").read_text())
            n = max(1, len(lines))
            rows = "".join(
                f'<span class="l step{" p" if ln.startswith("$ ") else ""}" data-d="{int(4 + i * (dur * 0.65 - 4) / n)}">{E(ln)}</span>'
                for i, ln in enumerate(lines))
            head = f'<h2 class="rv" data-d="0">{E(sc["heading"])}</h2>' if sc.get("heading") else ""
            body = f'<div {_cls(sc)}>{head}<div class="term">{rows}</div></div>'
    elif ty == "code":
        body = f'<div {_cls(sc)}><pre class="rv" data-d="0">{E(sc["code"])}</pre><div class="src">{E(sc["source"])}</div></div>'
    elif ty == "image":
        # cover + a zoom that keeps scene.focus centred (layout.zoom_plan); no letterbox bars
        z = f' data-z="{sc.get("zoom", 1.6)}"' if sc.get("focus") else ""
        head = f'<h2 class="rv" data-d="0">{E(sc["heading"])}</h2>' if sc.get("heading") else ""
        if sc.get("video"):  # a screen recording / gif: same cover + zoom, one still per scene frame
            pr, frames = _clip(sc, dur)
            imgs = "".join(f'<img src="{_img_uri(p)}"{z} style="display:{"block" if i == 0 else "none"}">'
                           for i, p in enumerate(frames))
            vm = E(json.dumps(_vmap(len(frames), dur, pr["fps"], fps)))
            body = f'<div {_cls(sc)}>{head}<div class="frame" data-vmap="{vm}">{imgs}</div></div>'
        else:
            body = f'<div {_cls(sc)}>{head}<div class="frame"><img src="{_img_uri(sc["image"])}"{z}></div></div>'
    cap = f'<div class="cap">{E(sc["caption"])}</div>' if sc.get("caption") else ""
    return f'<section class="scene" id="{E(sc["id"])}">{body}{cap}</section>'


def build_html(spec: dict) -> str:
    tl = S.timeline(spec)
    w, h = S.size(spec)
    th = spec["theme"]
    secs = "".join(_scene(sc, tl["fps"], tl["scenes"][i]["dur"], w, h, spec["aspect"])
                   for i, sc in enumerate(spec["scenes"]))
    # window/terminal chrome mixed from bg+fg, so it reads on a dark theme and on a light user palette
    panel, line = _mix(th["bg"], th["fg"], 0.06), _mix(th["bg"], th["fg"], 0.18)
    css = f":root{{--bg:{E(th['bg'])};--fg:{E(th['fg'])};--accent:{E(th['accent'])};--muted:{E(th['muted'])};" \
          f"--panel:{E(panel)};--line:{E(line)};--u:{min(w, h) / 100}px;{layout.css(spec['aspect'])}}}" + CSS
    js = JS % {"trans": tl["trans"], "scenes": json.dumps(tl["scenes"]),
               "motion": json.dumps(spec.get("motion") or "subtle"), "fps": tl["fps"]}
    return f'<!doctype html><meta charset="utf-8"><style>{css}</style><body>{secs}<script>{js}</script>'


def _block_external(route):
    u = route.request.url
    (route.continue_() if u.startswith(("file:", "data:", "about:")) else route.abort())


def _open(p, spec: dict, scale: float):
    w, h = S.size(spec)
    br = p.chromium.launch(args=ARGS, executable_path=config.chromium())
    ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale)
    ctx.route("**/*", _block_external)
    return br, ctx


# Measure each image frame and its natural size (all scenes made visible for the pass), so the zoom can
# be planned in Python from real layout numbers.
MEASURE_IMG_JS = """() => {const s=[...document.querySelectorAll('.scene')];
 s.forEach(e=>e.style.display='block');
 const m={};
 s.forEach(e=>{const i=e.querySelector('img[data-z]');
  if(i)m[e.id]={fw:i.clientWidth,fh:i.clientHeight,iw:i.naturalWidth,ih:i.naturalHeight}});
 s.forEach(e=>e.style.display='none');
 return m}"""

# Apply the planned cover box / pivot to each image, and hand the animation its numbers.
FIT_JS = """(items) => {items.forEach(([id,st])=>{document.querySelectorAll('#'+CSS.escape(id)+' img[data-z]').forEach(im=>
  Object.assign(im.style,{left:st.x+'px',top:st.y+'px',width:st.w+'px',height:st.h+'px',
  transformOrigin:st.ox+'px '+st.oy+'px'}))})}"""


def _zoom_map(pg, spec: dict) -> dict:
    """Plan the cover box and the zoom of every image scene from measured geometry (layout.zoom_plan),
    then size each <img> to the whole cover-cropped picture so the frame does the clipping."""
    meas = pg.evaluate(MEASURE_IMG_JS)
    out = {}
    for sc in spec["scenes"]:
        m = meas.get(sc["id"])
        if not (m and sc.get("focus") and m["iw"] and m["ih"]):
            continue
        p = layout.zoom_plan(m["fw"], m["fh"], m["iw"], m["ih"], sc["focus"], sc.get("zoom", 1.6))
        out[sc["id"]] = p
    if out:
        pg.evaluate(FIT_JS, [[sid, {**p["box"], "ox": p["origin"][0], "oy": p["origin"][1]}] for sid, p in out.items()])
    return out


def _page(ctx, spec: dict, h: str):
    d = config.WORK / "render" / h
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(build_html(spec))
    pg = ctx.new_page()
    pg.goto((d / "index.html").as_uri())
    plan = _zoom_map(pg, spec)
    pg.evaluate("m => { window.__ZOOM = m }", plan)
    return pg, plan


# Every box that carries content in one scene, as getBoundingClientRect sees it, plus whether its own
# content is cut off (scroll size > box). layout.audit_rects() judges these numbers.
MEASURE_JS = """(id) => {const el=document.getElementById(id); if(!el) return [];
 return [...el.querySelectorAll('h1,h2,.sub,li,pre,.term,.cap,.src,.win,.wbody,.tbar,.frame,span.l')].map(n=>{
  const r=n.getBoundingClientRect(),cs=getComputedStyle(n);   /* .frame/.wbody are crop boxes: their overflowing image is wanted */
  return {tag:n.tagName.toLowerCase()+((typeof n.className==='string'&&n.className)?'.'+n.className.split(' ')[0]:''),
   text:(n.textContent||'').replace(/\\s+/g,' ').trim().slice(0,40),
   rect:{x:r.x,y:r.y,w:r.width,h:r.height},
   vis:cs.display!=='none'&&cs.visibility!=='hidden'&&+cs.opacity>0.05,
   clip:!n.classList.contains('frame')&&!n.classList.contains('wbody')&&
    (n.scrollHeight>n.clientHeight+Math.max(2,parseFloat(cs.fontSize)*0.5)|| /* line-box/descender noise */
     n.scrollWidth>n.clientWidth+2)}})}"""


def _walk(h: str, shoot: bool, at_s: float | None = None) -> dict:
    """One browser pass: seek each scene to its review frame (or to `at_s` inside it), audit its boxes,
    and (optionally) shoot it. Identical frames give identical JPEG bytes, so `digest` answers
    "did the card stop moving?" without a decoder."""
    spec = S.load(h)
    tl = S.timeline(spec)
    rh = S.resolved_hash(spec)  # stills belong to this spec *and* this narration
    w, hh = S.size(spec)
    out = config.WORK / "stills" / rh
    res, findings = [], []
    with sync_playwright() as p:
        br, ctx = _open(p, spec, 0.4)
        pg, zoom = _page(ctx, spec, h)
        if shoot:
            out.mkdir(parents=True, exist_ok=True)
        for sc in tl["scenes"]:
            f = sc["start"] + min(sc["dur"] - 1, int(sc["dur"] * 0.75))
            if at_s is not None:  # a spot-check inside the scene, past the entrance
                f = sc["start"] + max(0, min(sc["dur"] - 1, int(at_s * tl["fps"])))
            pg.evaluate(f"seek({f})")
            els = pg.evaluate(MEASURE_JS, sc["id"])
            if sc["id"] in zoom:  # where the zoom puts the part of the capture the scene is about
                els.append({"tag": "focus", "text": "", "rect": zoom[sc["id"]]["focus_rect"], "vis": True})
            fs = layout.audit_rects(spec["aspect"], (w, hh), els, sc["id"])
            findings += fs
            item = {"scene": sc["id"], "frame": f, "findings": fs}
            if shoot:
                path = out / (f"{sc['id']}.jpg" if at_s is None else f"{sc['id']}-{at_s:g}s.jpg")
                pg.screenshot(path=str(path), type="jpeg", quality=70)
                item.update(path=str(path), bytes=path.stat().st_size,
                            digest=hashlib.sha256(path.read_bytes()).hexdigest()[:12])
            res.append(item)
        br.close()
    if shoot and at_s is None:  # a spot-check is not the review set
        (config.WORK / "specs" / f"{rh}.stills").write_text("ok")
    return {"stills": res, "findings": findings}


def stills_done(h: str) -> bool:
    """Stills are per *resolved* spec: re-narrating changes the timeline, so older stills don't count."""
    try:
        return (config.WORK / "specs" / f"{S.resolved_hash(S.load(h))}.stills").exists()
    except (OSError, ValueError):
        return False


def stills(h: str, at_s: float | None = None) -> list[dict]:
    """One small JPEG per scene plus the layout findings for that frame; `at_s` shoots that moment of
    every scene instead, and two runs with the same `digest` are pixel-identical frames."""
    return _walk(h, True, at_s)["stills"]


def audit(h: str) -> dict:
    """Geometry audit without screenshots: every content box against the frame and the safe zones."""
    spec = S.load(h)
    w, hh = S.size(spec)
    fs = _walk(h, False)["findings"]
    return {"status": "ok" if not fs else "warn", "aspect": spec["aspect"], "size": [w, hh],
            "warnings": len(fs), "findings": fs}


def _fmt(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def narration_cues(spec: dict) -> list[dict]:
    """Where each line lands in time: at its scene's start offset, but never before the previous line
    has finished -- scenes overlap by the transition, the voice-over must not (two voices at once).
    A cue also never runs into the next one, so the SRT never shows two captions at the same time."""
    tl = S.timeline(spec)
    man = S.audio_manifest(spec).get("scenes") or {}
    cues, prev_end = [], 0.0
    for sc, t in zip(spec["scenes"], tl["scenes"]):
        voiced = (sc.get("narration") or "").strip()
        text = voiced or sc.get("caption")
        if not text:
            continue
        a = man.get(sc["id"]) or {}
        spoken = float(a.get("duration_s") or 0) if voiced else 0.0
        start = max(t["start"] / tl["fps"], prev_end) if spoken else t["start"] / tl["fps"]
        cues.append({"id": sc["id"], "start_s": start, "dur_s": spoken or t["dur"] / tl["fps"],
                     "text": text, "path": a.get("path")})
        prev_end = start + spoken
    for c, nxt in zip(cues, cues[1:]):
        if nxt["start_s"] < c["start_s"] + c["dur_s"]:
            c["dur_s"] = max(1 / tl["fps"], nxt["start_s"] - c["start_s"])
    return cues


def srt(spec: dict) -> str:
    """Subtitles follow what is actually said: a narrated scene is cued for the *measured* manifest
    duration (the scene is usually longer), a silent one keeps its caption for the whole scene."""
    rows = [(c["start_s"], c["start_s"] + c["dur_s"], c["text"]) for c in narration_cues(spec)]
    return "".join(f"{i}\n{_fmt(a)} --> {_fmt(b)}\n{c}\n\n" for i, (a, b, c) in enumerate(rows, 1))


def narration_track(spec: dict) -> Path | None:
    """Lay the per-scene WAVs on one silent track at the cue offsets (the same timeline the frames use),
    so speech lands where its scene is on screen. None when nothing was narrated."""
    tl = S.timeline(spec)
    items = [(Path(c["path"]), c["start_s"]) for c in narration_cues(spec)
             if c["path"] and Path(c["path"]).is_file()]
    if not items:
        return None
    out = config.WORK / "out" / S.resolved_hash(spec) / "narration.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p, _ in items:
        cmd += ["-i", str(p)]
    delays = "".join(f"[{i}]adelay={int(round(s * 1000))}:all=1[a{i}];" for i, (_, s) in enumerate(items))
    mix = "".join(f"[a{i}]" for i in range(len(items)))
    total = tl["frames"] / tl["fps"]
    cmd += ["-filter_complex", f"{delays}{mix}amix=inputs={len(items)}:normalize=0:dropout_transition=0,"
            f"aresample=48000,apad[a]", "-map", "[a]", "-t", f"{total:.3f}", "-ac", "1", "-ar", "48000", str(out)]
    subprocess.run(cmd, check=True)
    return out


def _encoder(crf: str) -> list[str]:
    # Debian ffmpeg ships libx264; some distros (Fedora) only openh264, which needs a bitrate.
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" in enc:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf]
    return ["-c:v", "libopenh264", "-b:v", "6M" if crf == "18" else "2M"]


def render_sync(h: str, quality: str, job: dict) -> dict:
    spec = S.load(h)
    rh = S.resolved_hash(spec)
    if quality == "delivery" and not stills_done(h):
        raise RuntimeError("delivery render refused: run stills for this spec_hash first")
    tl = S.timeline(spec)
    w, h_ = S.size(spec)
    scale, crf = (0.5, "28") if quality == "draft" else (1.0, "18")
    ow, oh = int(w * scale), int(h_ * scale)
    out = config.WORK / "out" / rh
    out.mkdir(parents=True, exist_ok=True)
    mp4 = out / f"{quality}.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(tl["fps"]), "-i", "-",
         *_encoder(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)],
        stdin=subprocess.PIPE)
    dig = hashlib.sha256()
    try:
        with sync_playwright() as p:
            br, ctx = _open(p, spec, scale)
            pg, _ = _page(ctx, spec, h)
            for f in range(tl["frames"]):
                pg.evaluate(f"seek({f})")
                png = pg.screenshot(type="png")
                dig.update(png)
                ff.stdin.write(png)
                job["progress"] = round((f + 1) / tl["frames"], 3)
            br.close()
    finally:
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    # Mix (music bed + voice, ducked), normalise to -16 LUFS and mux: the picture is already made, so
    # this cannot change a single frame (and the poster is taken from the muxed file).
    mix = A.mux(mp4, spec, narration_track(spec), tl["frames"] / tl["fps"])
    credits = A.write_credits(spec, out)  # /work/CREDITS.txt + out/<hash>/CREDITS.txt for the description
    (out / f"{quality}.srt").write_text(srt(spec))
    poster = out / f"{quality}.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", f"select=eq(n\\,{tl['frames'] // 2})",
                    "-frames:v", "1", str(poster)], check=True)
    rec = {"video": str(mp4), "srt": str(out / f"{quality}.srt"), "poster": str(poster), "spec_hash": h,
           "resolved_hash": rh, "quality": quality, "width": ow, "height": oh, "fps": tl["fps"],
           "frames": tl["frames"], "frame_digest": dig.hexdigest()[:16],
           "credits": credits, "audio": (mix or {}).get("mix"), "mix": mix}
    (out / f"{quality}.receipt.json").write_text(json.dumps(rec, indent=1))
    return rec


JOBS: dict[str, dict] = {}


def start(h: str, quality: str) -> str:
    S.load(h)  # fail fast if spec missing
    jid = uuid.uuid4().hex[:8]
    job = JOBS[jid] = {"status": "running", "progress": 0.0}

    def run():
        try:
            job["result"] = render_sync(h, quality, job)
            job["status"] = "done"
        except Exception as e:  # surfaced via render_status
            job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"

    threading.Thread(target=run, daemon=True).start()
    return jid


def _duration(j: dict) -> float:
    """Container duration; a gif may not carry one, then frames / fps."""
    try:
        return float(j["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        a, b = j["streams"][0]["r_frame_rate"].split("/")
        return int(j["streams"][0].get("nb_frames") or 0) * int(b) / int(a)


def _probe(video: str) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_frames:format=duration", "-of", "json", video],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    a, b = j["streams"][0]["r_frame_rate"].split("/")
    return {"width": j["streams"][0]["width"], "height": j["streams"][0]["height"],
            "fps": int(a) / int(b), "duration": _duration(j)}


def _probe_audio(video: str) -> dict | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=codec_name,channels,sample_rate,duration:format=duration", "-of", "json", video],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    st = (j.get("streams") or [None])[0]
    if not st:
        return None
    dur = st.get("duration") or (j.get("format") or {}).get("duration")
    return {"codec": st.get("codec_name"), "channels": st.get("channels"),
            "sample_rate": int(st.get("sample_rate") or 0), "duration_s": round(float(dur or 0), 4)}


def narrated(spec: dict) -> bool:
    """The video promised a voice-over: the manifest has speech, or the spec still asks for it (narrate
    was never run -- then the MP4 is silent and that is an error, not a quiet video)."""
    return bool(S.audio_manifest(spec).get("scenes")) or any(
        (sc.get("narration") or "").strip() for sc in spec["scenes"])


def audio_findings(video_s: float, narrated: bool, au: dict | None,
                   voice: bool | None = None, bed: str | None = None) -> list[dict]:
    """A narrated video must carry the voice-over, and for exactly as long as the picture lasts: a short
    audio stream is a truncated last word, a long one a silent tail. `voice` is what the render receipt
    says went into the mix (None when the receipt predates it): any audio stream is not enough, a bed
    mixed without the voice would otherwise hide a missing voice-over. `bed` is the track the same
    receipt says was mixed in (mix.music): a silent spec with a music bed is a deliberate quiet video,
    so its audio is expected, not 'unexpected'."""
    if narrated and not au:
        return [{"severity": "error", "code": "no_audio",
                 "message": "spec has narration but the MP4 has no audio stream"}]
    if narrated and voice is False:
        return [{"severity": "error", "code": "no_voice",
                 "message": "spec has narration but the mix carries no voice-over (run narrate, then render again)"}]
    if au and abs(au["duration_s"] - video_s) > 0.1:
        return [{"severity": "error", "code": "audio_duration",
                 "message": f"audio {au['duration_s']:.3f}s != video {video_s:.3f}s (max 0.1s)"}]
    if au and not narrated and not bed:
        return [{"severity": "warn", "code": "unexpected_audio",
                 "message": "audio stream without narration or a music bed in the spec"}]
    return []


def _var(video: str, t: float) -> float:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                        "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    return statistics.pvariance(list(r.stdout)) if len(r.stdout) > 1 else 0.0


BLANK_WINDOW_S = 0.25  # how far around a blank-frame checkpoint to look: one frame is not a verdict
BLANK_VAR = 0.5  # below this the frame carries almost no picture


def _brightest_var(video: str, t0: float, total: float) -> float:
    """Picture content around `t0`, not at it: a checkpoint can land on a scene's entrance frame (opacity
    0) or on a crossfade tail, both of which are legitimately black. Sample +-BLANK_WINDOW_S and keep the
    richest sample -- the max, not a lower threshold, so an all-black video still fails."""
    return max(_var(video, max(0.0, min(total, t0 + d))) for d in (-BLANK_WINDOW_S, 0.0, BLANK_WINDOW_S))


def credits_finding(spec: dict, video: str | Path | None = None) -> dict | None:
    """A track that needs a credit must have reached a credit file with the render: the credit is the
    licence condition (CC BY), so a delivery that cannot show it is not shippable. The file written
    next to the video is checked first (a later render unlinks /work/CREDITS.txt), then /work."""
    m = spec.get("music")
    if not isinstance(m, dict) or not str(m.get("attribution") or "").strip():
        return None
    key = str(m.get("title") or m.get("attribution")).strip()[:40]
    paths = ([Path(video).parent / "CREDITS.txt"] if video else []) + [config.WORK / "CREDITS.txt"]
    for p in paths:
        try:
            txt = p.read_text()
        except OSError:
            continue
        if key and key in txt:
            return None
    return {"severity": "error", "code": "credits_missing",
            "message": f"no credit for {key!r} in {paths[0]}: re-render so the credit block ships "
                       f"with the video"}


def verify(video: str, h: str) -> dict:
    spec = S.load(h)
    tl = S.timeline(spec)
    findings = []
    p = safe_path(video)
    if not p.exists():
        return {"status": "error", "findings": [{"severity": "error", "code": "no_file", "message": str(p)}]}
    pr = _probe(str(p))
    recp = p.with_suffix(".receipt.json")
    rec = json.loads(recp.read_text()) if recp.exists() else {}
    aw, ah = S.size(spec)
    if rec.get("quality") == "delivery" or not rec:
        ew, eh = aw, ah  # a delivery render is exactly the delivery frame: 1080x1920 for 9:16
    else:
        ew, eh = rec.get("width", aw), rec.get("height", ah)  # a draft is the half-size preview
    if (pr["width"], pr["height"]) != (ew, eh):
        findings.append({"severity": "error", "code": "size",
                         "message": f"{pr['width']}x{pr['height']} != {ew}x{eh} for {spec['aspect']}"})
    if abs(pr["fps"] - tl["fps"]) > 0.01:
        findings.append({"severity": "error", "code": "fps", "message": f"{pr['fps']} != {tl['fps']}"})
    exp = tl["frames"] / tl["fps"]
    if abs(pr["duration"] - exp) > 1 / tl["fps"] + 1e-3:
        findings.append({"severity": "error", "code": "duration", "message": f"{pr['duration']:.3f}s != {exp:.3f}s"})
    for frac in (0.05, 0.5, 0.95):
        v = _brightest_var(str(p), exp * frac, pr["duration"])
        if v < BLANK_VAR:
            findings.append({"severity": "error", "code": "blank_frame", "message": f"luma variance {v:.2f} at {int(frac * 100)}%"})
    au = _probe_audio(str(p))
    voiced = narrated(spec)
    mix = rec.get("mix") or {}
    findings += audio_findings(pr["duration"], voiced, au, mix.get("voice"), mix.get("music"))
    cred = credits_finding(spec, p)
    if cred:
        findings.append(cred)
    loud = A.check(str(p), pr["duration"], voiced) if au else {"loudness": None, "silences": [], "findings": []}
    music = spec.get("music") if isinstance(spec.get("music"), dict) else {}
    return {"status": "error" if any(x["severity"] == "error" for x in findings) else "ok", "probe": pr,
            "aspect": spec["aspect"], "expected_size": [ew, eh],
            "expected_duration_s": round(exp, 3), "audio": au, "narrated": voiced,
            "music_license": music.get("license"), "credits": rec.get("credits"),
            "loudness": loud["loudness"], "silences": loud["silences"], "findings": findings}
