from __future__ import annotations

# Per-aspect template geometry, as fractions of the frame. In portrait the platform UI (TikTok, Reels,
# Shorts) covers the top ~10% and the bottom ~20% of the picture, so the content box is padded past both
# bands and the caption sits just above the bottom one instead of being buried under the UI.
LAYOUT = {
    "16:9": {"pad_x": 0.08, "pad_top": 0.08, "pad_bottom": 0.16, "cap_bottom": 0.05,
             "zone": {"top": 0.0, "bottom": 0.0, "side": 0.0}},
    "9:16": {"pad_x": 0.07, "pad_top": 0.10, "pad_bottom": 0.30, "cap_bottom": 0.21,
             "zone": {"top": 0.10, "bottom": 0.20, "side": 0.05}},
}
EPS = 1.0  # one CSS px of slack: sub-pixel layout noise is not overflow


def layout(aspect: str) -> dict:
    return LAYOUT.get(aspect) or LAYOUT["16:9"]


def css(aspect: str) -> str:
    """Custom properties the template's inset rules read, so one CSS serves every aspect."""
    lay = layout(aspect)
    return "".join(f"--{k.replace('_', '-')}:{lay[k] * 100:.2f}%;"
                   for k in ("pad_x", "pad_top", "pad_bottom", "cap_bottom"))


def outside(r: dict, w: float, h: float) -> bool:
    """True when a box leaves the frame on any side."""
    return (r["x"] < -EPS or r["y"] < -EPS
            or r["x"] + r["w"] > w + EPS or r["y"] + r["h"] > h + EPS)


def in_zone(r: dict, w: float, h: float, zone: dict) -> bool:
    """True when a box touches a reserved band (the areas a phone UI covers in portrait)."""
    if not any(zone.values()):
        return False
    return bool((zone["top"] and r["y"] < zone["top"] * h)
                or (zone["bottom"] and r["y"] + r["h"] > h - zone["bottom"] * h)
                or (zone["side"] and (r["x"] < zone["side"] * w or r["x"] + r["w"] > w - zone["side"] * w)))


def audit_rects(aspect: str, frame: tuple[float, float], els: list[dict], scene: str | None = None) -> list[dict]:
    """Flag boxes that leave the frame, sit in a reserved band, or have content cut off inside them.

    Pure: it takes the boxes Playwright measured (`rect`, `vis`, `clip`), so the rules can be tested
    without a browser. An image scene also passes one synthetic `focus` box: where the zoom puts the
    part of the capture the scene is about, which is what the old percentage transform-origin cropped.
    """
    lay, (w, h), out = layout(aspect), frame, []
    for e in els:
        r, tag = e.get("rect"), str(e.get("tag") or "?")
        if not r or e.get("vis") is False or r.get("w", 0) <= 0 or r.get("h", 0) <= 0:
            continue  # not laid out (hidden scene, faded-in element): it is not in this frame
        if tag == "focus":  # where the zoom put the part of the capture the scene is about
            centre = {"x": r["x"] + r["w"] / 2, "y": r["y"] + r["h"] / 2, "w": 0, "h": 0}
            if outside(centre, w, h):  # the promise is the centre; cover cannot fit a box bigger than the frame
                out.append({"severity": "warn", "code": "focus_outside", "scene": scene, "element": tag,
                            "message": f"the zoom pushes the focus centre outside the {int(w)}x{int(h)} frame",
                            "fix": "pick a smaller focus box, or a capture taken in this aspect"})
            continue  # a crop marker is not content of its own: no zone or overflow test
        label = f"{tag} '{e['text'][:32]}'" if e.get("text") else tag
        if outside(r, w, h):
            out.append({"severity": "warn", "code": "outside_frame", "scene": scene, "element": label,
                        "message": f"{label} leaves the {int(w)}x{int(h)} frame",
                        "fix": "shorten the text, lower the zoom or split the scene"})
        if in_zone(r, w, h, lay["zone"]):
            out.append({"severity": "warn", "code": "safe_zone", "scene": scene, "element": label,
                        "message": f"{label} sits inside the {aspect} safe zone "
                                   f"(top {lay['zone']['top']:.0%} / bottom {lay['zone']['bottom']:.0%})",
                        "fix": "keep content in the padded content box; captions go above the bottom band"})
        if e.get("clip"):
            out.append({"severity": "warn", "code": "clipped_content", "scene": scene, "element": label,
                        "message": f"{label} has content cut off inside its own box",
                        "fix": "fewer lines or shorter text for this aspect"})
    return out


def cover(fw: float, fh: float, iw: float, ih: float) -> tuple[float, float, float]:
    """object-fit:cover: scale and the (<=0) offsets of the image content inside a fw x fh frame."""
    if fw <= 0 or fh <= 0 or iw <= 0 or ih <= 0:
        return 1.0, 0.0, 0.0
    s = max(fw / iw, fh / ih)
    return s, (fw - iw * s) / 2, (fh - ih * s) / 2


def _zlimit(lo: float, hi: float, half: float) -> float:
    """Largest zoom that keeps [lo, hi] (offsets from the pivot) inside the [-half, half] half-frame."""
    lim = [(-half / lo) if lo < 0 else float("inf"), (half / hi) if hi > 0 else float("inf")]
    return min(lim)


def zoom_plan(fw: float, fh: float, iw: float, ih: float, focus: dict, zoom: float = 1.6) -> dict:
    """Cover the frame with the capture, bring its focus box to the middle, then zoom about the centre.

    The page applies `translate(-z*ox, -z*oy) scale(z)` about the frame centre, so the pivot below lands
    on the frame centre for every z -- which is what the old `transform-origin: focus%` got wrong
    whenever contain letterboxed the capture. The pivot is clamped to the part of the image that can be
    centred while the image still covers the frame (cover cannot pan past an edge, or a gap shows), and
    z is clamped so the focus box stays in the picture.
    """
    s, x0, y0 = cover(fw, fh, iw, ih)
    dw, dh = iw * s, ih * s
    fw2, fh2 = focus["w"] * dw, focus["h"] * dh
    fx0, fy0 = x0 + focus["x"] * dw, y0 + focus["y"] * dh
    cx, cy = fx0 + fw2 / 2, fy0 + fh2 / 2
    px = min(max(cx, x0 + fw / 2), x0 + dw - fw / 2)  # the image must keep covering the frame
    py = min(max(cy, y0 + fh / 2), y0 + dh - fh / 2)
    zmax = max(1.0, min(_zlimit(fx0 - px, cx + fw2 / 2 - px, fw / 2),
                        _zlimit(fy0 - py, cy + fh2 / 2 - py, fh / 2)))
    z = max(1.0, min(float(zoom), zmax))
    hw, hh = fw / 2, fh / 2
    return {"ox": round(px - hw, 2), "oy": round(py - hh, 2), "z": round(z, 3),
            "frame": [fw, fh], "img": [iw, ih], "zoom": float(zoom),
            # the <img> box becomes the whole cover-cropped content, so the frame (not the img's own box)
            # does the clipping and a translate really pans the picture
            "box": {"x": round(x0, 1), "y": round(y0, 1), "w": round(dw, 1), "h": round(dh, 1)},
            "origin": [round(px - x0, 1), round(py - y0, 1)],
            "focus_rect": {"x": hw + z * (fx0 - px), "y": hh + z * (fy0 - py), "w": z * fw2, "h": z * fh2}}
