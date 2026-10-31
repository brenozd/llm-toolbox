from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import os
import shutil
import statistics
import time
import subprocess
import threading
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import audio as A, config, cues, layout, sfx as SFX, spec as S, tts as TTS
from .safety import safe_path

ARGS = ["--disable-gpu", "--disable-dev-shm-usage", "--disable-lcd-text", "--font-render-hinting=none",
        "--force-color-profile=srgb", "--hide-scrollbars", "--no-sandbox"]
E = html.escape
# The animatic quality profile: the rough cut that judges rhythm before a single capture exists. Same
# template, same voice, a cheap picture -- 360p (short side), 15 fps, a printed ANIMATIC watermark and
# no music, so nobody mistakes it for the delivery.
ANIMATIC = {"short_side": 360, "fps": 15, "watermark": "ANIMATIC", "crf": "30"}
CUE_MIN_VISIBLE_S = 1.5  # a cue reveal this close to the scene's end is a flash, not a beat
ANIMATIC_CAVEAT = ("TTS is more regular than a human: these are the pauses the synth left, not the pace a "
                   "reading will have. Judge structure and order here; recompute with the final voice before "
                   "locking a cut.")

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
.wm{position:fixed;right:2%;top:2%;z-index:99;font-family:'DejaVu Sans Mono',monospace;font-size:calc(var(--u)*3.4);letter-spacing:.14em;color:var(--fg);opacity:.6;border:2px solid var(--fg);border-radius:calc(var(--u)*.6);padding:calc(var(--u)*.4) calc(var(--u)*1.2);background:rgba(0,0,0,.25)}
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
    # JPEG 4:4:4 keeps monospace text crisp at a fraction of PNG's size; a gif may carry alpha, so it stays PNG
    ext = "png" if p.suffix.lower() == ".gif" else "jpg"
    key = hashlib.sha256(f"{config.RENDER_VERSION}|{ext}|{p}|{st.st_size}|{st.st_mtime_ns}|{n}|{fps}".encode()).hexdigest()[:12]
    root = config.WORK / "frames"
    d = root / key
    have = sorted(d.glob(f"*.{ext}")) if d.is_dir() else []
    if len(have) < n:
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(f"*.{ext}"):
            old.unlink()
        enc = ["-c:v", "png"] if ext == "png" else ["-c:v", "mjpeg", "-q:v", "2", "-pix_fmt", "yuvj444p"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", f"fps={fps},scale='min(iw,1920)':-2",
                        *enc, "-frames:v", str(n), str(d / f"%04d.{ext}")], check=True)
        have = sorted(d.glob(f"*.{ext}"))
    os.utime(d)  # a lease: a render in progress is never the oldest
    _evict_frames(root, keep=d)
    return [str(x) for x in have[:n]]


def _evict_frames(root: Path, keep: Path, newest: int = 8, min_age_s: int = 3600) -> None:
    """Frame dirs only grow otherwise. Drop old ones beyond the newest few; never one a render may be reading."""
    try:
        dirs = sorted((x for x in root.iterdir() if x.is_dir()), key=lambda x: x.stat().st_mtime, reverse=True)
    except OSError:  # another render evicted at the same time
        return
    for x in dirs[newest:]:
        if x != keep and time.time() - x.stat().st_mtime > min_age_s:
            shutil.rmtree(x, ignore_errors=True)


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


def _rv(instant: bool, d: int, cls: str = "") -> str:
    """The entrance attributes of a text box. `instant` drops them entirely: an animatic card is a working
    document to be read from its first frame, not an animation to be watched enter."""
    return f' class="{cls}"' if instant and cls else "" if instant else f' class="{cls + " " if cls else ""}rv" data-d="{d}"'


def _scene(sc: dict, fps: int, dur: int, w: int = 1920, h: int = 1080, aspect: str = "16:9",
           instant: bool = False, cue_d: dict | None = None) -> str:
    cue_d = cue_d or {}
    ty, body = sc["type"], ""
    if ty == "title":
        body = f'<div {_cls(sc)}><h1{_rv(instant, 0)}>{E(sc["title"])}</h1><p{_rv(instant, 8, "sub")}>{E(sc.get("subtitle", ""))}</p></div>'
    elif ty == "bullets":
        lis = "".join(f'<li{_rv(instant, cue_d.get(i, 8 + i * 10))}>{E(x)}</li>' for i, x in enumerate(sc["items"]))
        body = f'<div {_cls(sc)}><h2{_rv(instant, 0)}>{E(sc["heading"])}</h2><ul>{lis}</ul></div>'
    elif ty == "terminal":
        if sc.get("video"):
            body = _terminal_video(sc, fps, dur, w, h, aspect)
        else:
            lines = sc.get("lines") or json.loads((config.WORK / "captures" / sc["capture_id"] / "lines.json").read_text())
            n = max(1, len(lines))
            rows = "".join(
                f'<span class="l step{" p" if ln.startswith("$ ") else ""}" data-d="{cue_d.get(i, int(4 + i * (dur * 0.65 - 4) / n))}">{E(ln)}</span>'
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


def cue_delays(spec: dict, tl: dict) -> dict[str, dict]:
    """{scene id: {item: entrance frame}} from scene.cues and the narration's word timings. Off with
    STORYBOARD_CUES=0; a spec without cues gets {} and the fixed stagger it always had."""
    if os.environ.get("STORYBOARD_CUES") == "0" or not any(isinstance(sc.get("cues"), list) for sc in spec["scenes"]):
        return {}
    man = S.audio_manifest(spec).get("scenes") or {}
    starts = {c["id"]: c["start_s"] for c in narration_cues(spec)}
    t0 = {t["id"]: t["start"] / tl["fps"] for t in tl["scenes"]}
    out = {}
    for sc in spec["scenes"]:
        a = man.get(sc["id"]) or {}
        if not sc.get("cues") or sc["id"] not in starts or not a.get("path"):
            continue
        words = a.get("words")
        if not words:  # a manifest written before cues existed
            words = TTS.words_of(sc["narration"], Path(a["path"]), spec.get("say"))
        out[sc["id"]] = cues.delays(sc, words, starts[sc["id"]] - t0[sc["id"]], tl["fps"])
    return out


def cue_late_findings(spec: dict, tl: dict) -> list[dict]:
    """Warn-only: a cue that reveals its item so late it barely reaches the screen. Less than
    CUE_MIN_VISIBLE_S before the scene ends is a flash, and a reveal at/after the end is never seen.
    A spec without cues (or without a narration manifest) has nothing to place and gets []."""
    out, cd = [], cue_delays(spec, tl)
    trans, last = tl.get("trans") or 0, len(tl["scenes"]) - 1
    for i, (sc, t) in enumerate(zip(spec["scenes"], tl["scenes"])):
        d = cd.get(sc.get("id")) or {}
        # the next scene slides in over the last `trans` frames: those are not this scene's screen time
        dur = (t["dur"] - (trans if i < last else 0)) / tl["fps"]
        for item, frames in sorted(d.items()):
            at, left = frames / tl["fps"], dur - frames / tl["fps"]
            if left >= CUE_MIN_VISIBLE_S:
                continue
            out.append({"severity": "warn", "code": "cue_late", "scene": sc.get("id"), "item": item,
                        "at_s": round(at, 2), "left_s": round(left, 2),
                        "message": f"item {item} is revealed at {at:.1f}s, {left:.1f}s before the scene ends"
                                   if left > 0 else
                                   f"item {item} is revealed at {at:.1f}s, past the scene's {dur:.1f}s end",
                        "fix": "shorten the narration before that phrase, raise duration_s, or cue an earlier "
                               "phrase (a negative lead_ms also pulls the reveal forward)"})
    return out


def cue_times(spec: dict, tl: dict) -> dict[str, dict[int, float]]:
    """{scene id: {cue index: seconds on the video timeline}} for every cue whose phrase is said exactly once."""
    man = S.audio_manifest(spec).get("scenes") or {}
    starts = {c["id"]: c["start_s"] for c in narration_cues(spec)}
    out = {}
    for sc in spec["scenes"]:
        a = man.get(sc["id"]) or {}
        if not any(isinstance(e, dict) and isinstance(e.get("at"), str) for e in sc.get("sfx") or []) or \
                sc["id"] not in starts or not a.get("path"):
            continue
        words = a.get("words") or TTS.words_of(sc["narration"], Path(a["path"]), spec.get("say"))
        out[sc["id"]] = cues.times(sc, words, starts[sc["id"]])
    return out


def build_html(spec: dict, tl: dict | None = None, watermark: str | None = None,
               size: tuple[int, int] | None = None, instant: bool = False) -> str:
    """The timeline as one static page. `tl`, `watermark`, `size` and `instant` are the animatic's knobs:
    its own frame rate/timeline (see `animatic_timeline`), a printed watermark, a smaller frame, and text
    that is readable from frame 0; the delivery render passes none of them and gets the page it always got."""
    tl = tl or S.timeline(spec)
    w, h = size or S.size(spec)
    th = spec["theme"]
    cd = {} if instant else cue_delays(spec, tl)
    secs = "".join(_scene(sc, tl["fps"], tl["scenes"][i]["dur"], w, h, spec["aspect"], instant, cd.get(sc["id"]))
                   for i, sc in enumerate(spec["scenes"]))
    # window/terminal chrome mixed from bg+fg, so it reads on a dark theme and on a light user palette
    panel, line = _mix(th["bg"], th["fg"], 0.06), _mix(th["bg"], th["fg"], 0.18)
    css = f":root{{--bg:{E(th['bg'])};--fg:{E(th['fg'])};--accent:{E(th['accent'])};--muted:{E(th['muted'])};" \
          f"--panel:{E(panel)};--line:{E(line)};--u:{min(w, h) / 100}px;{layout.css(spec['aspect'])}}}" + CSS
    js = JS % {"trans": tl["trans"], "scenes": json.dumps(tl["scenes"]),
               "motion": json.dumps(spec.get("motion") or "subtle"), "fps": tl["fps"]}
    mark = f'<div class="wm">{E(watermark)}</div>' if watermark else ""
    return f'<!doctype html><meta charset="utf-8"><style>{css}</style><body>{secs}{mark}<script>{js}</script>'


def _block_external(route):
    u = route.request.url
    (route.continue_() if u.startswith(("file:", "data:", "about:")) else route.abort())


def _open(p, spec: dict, scale: float, size: tuple[int, int] | None = None):
    w, h = size or S.size(spec)
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


def _page(ctx, spec: dict, h: str, tl: dict | None = None, watermark: str | None = None,
          size: tuple[int, int] | None = None, instant: bool = False):
    d = config.WORK / "render" / h
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(build_html(spec, tl, watermark, size, instant))
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
        voiced = S._narration(sc)
        text = voiced or sc.get("caption")
        if not text:
            continue
        a = man.get(sc["id"]) or {}
        spoken = float(a.get("duration_s") or 0) if voiced else 0.0
        # audio_lead_s (J/L-cut): the voice comes in before the picture cuts, but never over the previous line
        lead = min(S._num(sc, "audio_lead_s"), S.LEAD_MAX_S)
        start = max(t["start"] / tl["fps"] - lead, prev_end, 0.0) if spoken else t["start"] / tl["fps"]
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


def narration_track(spec: dict, dest: Path | None = None) -> Path | None:
    """Lay the per-scene WAVs on one silent track at the cue offsets (the same timeline the frames use),
    so speech lands where its scene is on screen. None when nothing was narrated. `dest` lets the animatic
    keep its voice track outside `out/<resolved_hash>/` (an animatic is not a delivery)."""
    tl = S.timeline(spec)
    items = [(Path(c["path"]), c["start_s"]) for c in narration_cues(spec)
             if c["path"] and Path(c["path"]).is_file()]
    if not items:
        return None
    out = dest or config.WORK / "out" / S.resolved_hash(spec) / "narration.wav"
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


def pace_map(spec: dict) -> dict:
    """How the voice paces each scene, measured from the WAVs the manifest recorded: `dur_s` is the scene on
    the timeline, `words`/`wps` the spoken line, `lead_s` the silence before it starts (the previous line
    was still speaking) and `tail_s` the time the picture holds after it ends -- the room a shot has.

    A silent scene has no line: `lead_s` 0 and `tail_s` = the whole scene (nobody speaks, the picture
    holds). The caveat is part of the answer because a synth is more regular than a reader."""
    tl = S.timeline(spec)
    man = S.audio_manifest(spec).get("scenes") or {}
    cues = {c["id"]: c for c in narration_cues(spec)}
    rows = []
    for sc, t in zip(spec["scenes"], tl["scenes"]):
        sid = sc.get("id")
        start, dur = t["start"] / tl["fps"], t["dur"] / tl["fps"]
        voice = float((man.get(sid) or {}).get("duration_s") or 0.0)
        words = len(S._narration(sc).split())
        cue = cues.get(sid) if voice > 0 else None
        missing = bool(words) and voice <= 0  # narrated but never synthesised: not "silent"
        lead = max(0.0, (cue["start_s"] - start) if cue else 0.0)
        tail = max(0.0, dur - lead - voice) if cue else 0.0 if missing else dur
        rows.append({"id": sid, "type": sc.get("type"), "dur_s": round(dur, 3), "words": words,
                     "wps": round(words / voice, 2) if words and voice > 0 else 0.0,
                     "lead_s": round(lead, 3), "tail_s": round(tail, 3), "voice_s": round(voice, 3),
                     **({"voice_missing": True} if missing else {})})
    return {"scenes": rows, "total_s": round(tl["frames"] / tl["fps"], 2),
            "words": sum(r["words"] for r in rows), "caveat": ANIMATIC_CAVEAT}


PLACEHOLDER = {"pt-BR": {"capture": "[captura: {what} — {dur:.1f}s]", "card": "[cartão: {what}]"},
               "en": {"capture": "[capture: {what} — {dur:.1f}s]", "card": "[card: {what}]"}}
CAPTURE_KIND = {"pt-BR": {"terminal": "sessão de terminal", "image": "print da tela", "code": "código"},
                "en": {"terminal": "terminal session", "image": "screenshot", "code": "code"}}
SHOT_TOOL = {"terminal": "capture_terminal_session", "image": "capture_web", "code": "extract_code"}
SHOT_NEED = {
    "terminal": "record the commands of this scene as a real session (typing staged, output real)",
    "image": "screenshot the screen this scene is about, from the moment the line starts",
    "code": "extract the lines that prove the claim",
}


def animatic_size(spec: dict) -> tuple[int, int]:
    """360p on the short side (16:9 -> 640x360, 9:16 -> 360x640), even on both axes for yuv420p."""
    w, h = S.size(spec)
    s = ANIMATIC["short_side"] / min(w, h)
    return (round(w * s / 2) * 2, round(h * s / 2) * 2)


def animatic_timeline(tl: dict) -> dict:
    """The same scenes in the same seconds at the animatic frame rate, with hard cuts (trans=0): a card
    needs no crossfade, and because the seconds are untouched the delivery's voice cues still line up."""
    fps, o = ANIMATIC["fps"], tl["fps"]
    scenes = [{"id": t["id"], "start": round(t["start"] * fps / o),
               "dur": max(1, round(t["dur"] * fps / o))} for t in tl["scenes"]]
    return {"fps": fps, "trans": 0, "scenes": scenes,
            "frames": max((s["start"] + s["dur"] for s in scenes), default=0)}


def animatic_placeholder(sc: dict, dur_s: float, lang: str) -> str:
    """The visual column of the AV script, written out: what still has to be captured, and for how long."""
    w = PLACEHOLDER.get(lang) or PLACEHOLDER["en"]
    ty = sc.get("type") or "title"
    what = (sc.get("heading") or sc.get("title") or sc.get("source")
            or Path(str(sc.get("image") or sc.get("video") or "")).name or sc.get("id") or "")
    if ty in ("terminal", "image", "code"):
        kind = (CAPTURE_KIND.get(lang) or CAPTURE_KIND["en"])[ty]
        return w["capture"].format(what=f"{kind}: {what}"[:64], dur=dur_s)
    return w["card"].format(what=str(what)[:64])


def animatic_card(sc: dict, dur_s: float, lang: str) -> dict:
    """One scene as a readable card: the placeholder tells the reviewer what the shot will be, and the line
    that is spoken stays on screen so the round judges the words against the structure."""
    ty = sc.get("type") or "title"
    head = sc.get("heading") or sc.get("title") or sc.get("source") or sc.get("id") or ""
    items = [animatic_placeholder(sc, dur_s, lang)]
    line = (S._narration(sc) or sc.get("caption") or "").strip()
    if line:
        items.append(f'"{line}"')
    return {"id": sc["id"], "type": "bullets", "align": "left",
            "heading": f"{ty} · {head}"[:72], "items": items}


def animatic_cards(spec: dict, tl: dict) -> dict:
    """The card spec: every scene becomes text, with no image/video/capture_id key at all -- so an animatic
    never needs a capture (and never shows a stale one). Music is dropped: a rough cut judges the voice."""
    lang = spec.get("lang") if spec.get("lang") in PLACEHOLDER else "en"
    durs = {t["id"]: t["dur"] / tl["fps"] for t in tl["scenes"]}
    return {**spec, "fps": ANIMATIC["fps"], "transition_s": 0, "music": None,
            "scenes": [animatic_card(sc, durs.get(sc.get("id"), float(sc.get("duration_s") or 0)), lang)
                       for sc in spec["scenes"]]}


def animatic_path(spec: dict) -> Path:
    """Where a rough cut lives: /work/animatic/<animatic hash>_ANIMATIC.mp4, outside out/<resolved_hash>/
    (a delivery directory must never contain a placeholder video) and named so it cannot be mistaken."""
    return config.WORK / "animatic" / f"{S.resolved_hash(spec, stage='animatic')}_ANIMATIC.mp4"


def animatic(h: str, job: dict | None = None) -> dict:
    """Rough cut of spec `h`: the *delivery* render path (same template, same frame loop, same mux) run
    with the animatic profile -- 360p, 15 fps, an ANIMATIC watermark, no music and no capture: each scene
    is a card with its visual placeholder and its own line's WAV. The MP4 and its receipt land in
    /work/animatic/, outside out/<resolved_hash>/, and carry the `stage="animatic"` id, so a rough cut can
    never be mistaken for the final video. Returns the path plus the pace_map the round is judged on."""
    job = job if job is not None else {}
    job.update(status="running", progress=0.0)
    spec = S.load(h)
    tl = S.timeline(spec)
    atl = animatic_timeline(tl)
    cards = animatic_cards(spec, tl)
    w, hh = animatic_size(spec)
    rh = S.resolved_hash(spec, stage="animatic")
    mp4 = animatic_path(spec)
    out = mp4.parent
    out.mkdir(parents=True, exist_ok=True)
    mp4.unlink(missing_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(atl["fps"]), "-i", "-",
         *_encoder(ANIMATIC["crf"]), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)],
        stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            br, ctx = _open(p, cards, 1.0, size=(w, hh))
            pg, _ = _page(ctx, cards, rh, tl=atl, watermark=ANIMATIC["watermark"], size=(w, hh), instant=True)
            for f in range(atl["frames"]):
                pg.evaluate(f"seek({f})")
                ff.stdin.write(pg.screenshot(type="png"))
                job["progress"] = round((f + 1) / atl["frames"], 3)
            br.close()
    finally:
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    total = atl["frames"] / atl["fps"]
    work = out / f"{rh}.work"  # per-cut scratch dir, so two cuts never share a narration.wav/mix.wav
    work.mkdir(exist_ok=True)
    voice = narration_track(spec, dest=work / "narration.wav")
    mix = A.mux(mp4, cards, voice, total, wav=work / "mix.wav")  # cards.music is None: a rough cut carries the voice and nothing else
    pm = pace_map(spec)
    rec = {"video": str(mp4), "spec_hash": h, "resolved_hash": S.resolved_hash(spec, stage="animatic"),
           "quality": "animatic", "width": w, "height": hh, "fps": atl["fps"], "frames": atl["frames"],
           "duration_s": round(total, 2), "audio": bool(mix), "music": None, "pace_map": pm}
    (mp4.with_suffix(".json")).write_text(json.dumps(rec, indent=1))
    job.update(status="done", progress=1.0)
    return {"status": "ok", **{k: v for k, v in rec.items() if k not in ("video", "pace_map")},
            "video": str(mp4), "pace_map": pm,
            "note": "rough cut: placeholders, 360p, 15 fps, no music -- not a delivery. "
                    "Run stills + render(quality='delivery') for the final video."}


def shot_list(h: str) -> dict:
    """The captures this AV script still needs, scene by scene and in playback order, each with the time the
    voice left for it: `hold_s` is what the shot has on screen after its line ends, `silent_s` the whole
    silence of the scene (lead + tail). That number -- not 'whatever fits' -- is what a capture has to
    fill, and `evidence` (file:line) is the claim the shot has to prove when the script carries one."""
    spec = S.load(h)
    tl = S.timeline(spec)
    plan = S.plan(spec)
    pm = {r["id"]: r for r in pace_map(spec)["scenes"]}
    rows, warns = [], []
    for sc, t in zip(spec["scenes"], tl["scenes"]):
        sid, ty = sc.get("id"), sc.get("type")
        p = pm.get(sid) or {}
        have = ("video" if sc.get("video") else "image" if sc.get("image")
                else "lines" if (sc.get("lines") or sc.get("capture_id")) else "code" if sc.get("code") else None)
        need, tool = SHOT_NEED.get(ty), SHOT_TOOL.get(ty)
        if have:  # already captured: the row still says what it has and how long it holds
            need = None
        hold = float(p.get("tail_s") or 0.0)
        row = {"id": sid, "type": ty, "role": plan[sid].get("role") if isinstance(plan.get(sid), dict) else None,
               "at_s": round(t["start"] / tl["fps"], 2), "dur_s": p.get("dur_s"),
               "voice_s": p.get("voice_s"), "hold_s": round(hold, 3),
               "silent_s": round(float(p.get("lead_s") or 0.0) + hold, 3),
               "need": need, "tool": None if have else tool, "have": have,
               "evidence": sc.get("evidence") if isinstance(sc.get("evidence"), str) else None}
        ev = row["evidence"]
        if ty == "code" and ev:  # the extract_code call this row stands for
            f, _, ln = ev.partition(":")
            row["call"] = {"tool": "extract_code", "args": {"path": f, "lines": ln or "1"}}
        if need and hold < 1.0:
            warns.append({"severity": "warn", "code": "shot_no_hold", "scene": sid,
                          "message": f"the voice leaves {hold:.1f}s after the line",
                          "fix": "give the scene a longer tail (duration_s) or cut the shot: less than a "
                                 "second on screen is a flash, not a shot"})
        rows.append(row)
    warns.extend(cue_late_findings(spec, tl))
    need_n = sum(1 for r in rows if r["need"])
    return {"status": "ok", "spec_hash": h, "duration_s": round(tl["frames"] / tl["fps"], 2),
            "captures_needed": need_n, "scenes": rows, "warnings": warns,
            "note": ("the voice sets the clock: at_s and hold_s come from the narration manifest, so run "
                     "narrate before this list is final") if not S.audio_manifest(spec).get("scenes") else
                    "each row is one capture call; hold_s is the time the voice left for it"}


def _encoder(crf: str) -> list[str]:
    # Debian ffmpeg ships libx264; some distros (Fedora) only openh264, which needs a bitrate.
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" in enc:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf]
    return ["-c:v", "libopenh264", "-b:v", "6M" if crf == "18" else "2M"]


def render_sync(h: str, quality: str, job: dict) -> dict:
    if quality == "animatic":  # one render path, two profiles: a rough cut is never a delivery
        return animatic(h, job)
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
    # Mix (music bed + voice, ducked), normalise to the spec's target (-14 LUFS by default) and mux: the picture is
    # already made, so this cannot change a single frame (and the poster is taken from the muxed file).
    mix = A.mux(mp4, spec, narration_track(spec), tl["frames"] / tl["fps"],
                sfx=SFX.track(spec, tl, out / f"{rh}.work" / "sfx.wav", cue_times(spec, tl)))
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
    job = JOBS[jid] = {"status": "running", "progress": 0.0, "started_at": time.time()}

    def run():
        try:
            job["result"] = render_sync(h, quality, job)
            job["status"] = "done"
        except Exception as e:  # surfaced via render_status
            job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
        finally:
            job["finished_at"] = time.time()  # elapsed_s stops counting when the job stops

    threading.Thread(target=run, daemon=True).start()
    return jid


def status(jid: str) -> dict:
    """One job as render_status reports it: the job dict plus `elapsed_s`, the wall seconds since
    `start` (still counting while it runs, frozen once it ends), so a caller can tell a slow render
    from a stuck one instead of staring at progress alone."""
    j = JOBS.get(jid)
    if not j:
        return {"status": "error", "message": "unknown job_id"}
    end = j.get("finished_at") or time.time()
    return {**j, "elapsed_s": round(max(0.0, end - j.get("started_at", end)), 2)}


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
        S._narration(sc) for sc in spec["scenes"])


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
    if isinstance(m, dict) and str(m.get("attribution") or "").strip():
        key = str(m.get("title") or m.get("attribution")).strip()[:40]
    elif TTS.voices.credits(spec):  # a CC BY voice: the credit names it
        key = "Voice credits"
    else:
        return None
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
    loud = A.check(str(p), pr["duration"], voiced, A.target_lufs(spec)) if au else {"loudness": None, "silences": [], "findings": []}
    findings += loud["findings"]  # the delivery bar (loudness, true peak, silences) was measured but never reported
    margin = mix.get("duck_margin_db")
    if isinstance(margin, (int, float)) and margin < A.DUCK_MARGIN_MIN_DB:
        findings.append({"severity": "warn", "code": "duck_margin", "message":
                         f"the voice sits only {margin:g} dB above the bed while it speaks (want >= {A.DUCK_MARGIN_MIN_DB:g})",
                         "fix": "lower music.volume_db or raise music.duck, then render again"})
    music = spec.get("music") if isinstance(spec.get("music"), dict) else {}
    return {"status": "error" if any(x["severity"] == "error" for x in findings) else "ok", "probe": pr,
            "aspect": spec["aspect"], "expected_size": [ew, eh],
            "expected_duration_s": round(exp, 3), "audio": au, "narrated": voiced,
            "music_license": music.get("license"), "credits": rec.get("credits"),
            "loudness": loud["loudness"], "silences": loud["silences"], "duck_margin_db": margin,
            "findings": findings}
