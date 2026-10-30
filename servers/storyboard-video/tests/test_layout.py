import json
import shutil
import subprocess

import pytest

from storyboard_video_mcp import config, layout, render, spec as S


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def codes(fs):
    return [f["code"] for f in fs]


# --- formats and capture geometry ---------------------------------------------------------------

def test_capture_geometry_per_format():
    assert S.fmt("16:9")["viewport"] == {"width": 1440, "height": 810}
    assert S.fmt("9:16")["viewport"] == {"width": 540, "height": 960}
    assert S.fmt("9:16")["device_scale_factor"] == 2
    # 16:9 matches the content-box aspect (2.4:1) at a legible font: a taller grid would shrink the text
    assert (S.fmt("16:9")["cols"], S.fmt("16:9")["rows"], S.fmt("16:9")["font"]) == (80, 16, 22)
    assert (S.fmt("9:16")["cols"], S.fmt("9:16")["rows"]) == (44, 28)
    assert S.fmt("9:16")["gui"] == "720x1280" and S.fmt("9:16")["max_cols"] == 40
    with pytest.raises(ValueError):
        S.fmt("4:3")


def test_capture_tools_default_to_the_format(tmp_path, monkeypatch):
    from storyboard_video_mcp import capture
    monkeypatch.setattr(config, "ALLOW_EXEC", False)
    with pytest.raises(PermissionError):
        capture.capture_gui("app", aspect="9:16")


def test_capture_terminal_trims_to_the_format_and_records_it(tmp_path, monkeypatch):
    from storyboard_video_mcp import capture
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    r = capture.capture_terminal("printf '%s\\n' " + "x" * 60, aspect="9:16")
    assert r["status"] == "ok"
    assert max(len(ln) for ln in r["lines"]) == 40
    meta = S.capture_meta(r["capture_id"])
    assert meta == {"tool": "capture_terminal", "aspect": "9:16", "cols": 40, "max_lines": 16}


# --- reframe / portrait rules --------------------------------------------------------------------

def test_reformat_to_portrait_drops_bullets_and_trims_lines():
    long = "x" * 60
    s = mk(scenes=[{"id": "b", "type": "bullets", "heading": "Why", "items": ["a", "b", "c", "d", "e"]},
                   {"id": "t", "type": "terminal", "lines": ["$ ok", "$ " + long]}])
    r = S.reformat(s, "9:16")
    assert r["spec"]["aspect"] == "9:16"
    assert r["spec"]["scenes"][0]["items"] == ["a", "b", "c", "d"]
    assert len(r["spec"]["scenes"][1]["lines"][1]) == 40 and r["spec"]["scenes"][1]["lines"][1].endswith("…")
    assert {c["field"] for c in r["changes"]} == {"items", "lines"}
    assert r["changes"][0]["dropped"] == ["e"]
    # 16:9 keeps all five bullets, and reformatting does not invent changes
    back = S.reformat(r["spec"], "16:9")
    assert back["spec"]["aspect"] == "16:9"
    assert back["changes"] == []


def test_reformat_reports_captures_that_must_be_redone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    for cid, aspect in (("wide01", "16:9"), ("port02", "9:16")):
        d = tmp_path / "captures" / cid
        d.mkdir(parents=True)
        (d / "capture.json").write_text(json.dumps({"tool": "capture_web", "aspect": aspect}))
    s = mk(scenes=[{"id": "w", "type": "image", "image": str(tmp_path / "captures" / "wide01" / "w1.png")},
                   {"id": "p", "type": "image", "image": str(tmp_path / "captures" / "port02" / "p1.png")}])
    r = S.reformat(s, "9:16")
    assert [x["capture_id"] for x in r["recaptures"]] == ["wide01"]
    redo = r["recaptures"][0]
    assert redo["scene"] == "w" and redo["have"] == "16:9" and "9:16" not in redo["reason"].replace("not 9:16", "")
    assert redo["redo_with"]["viewport"] == {"width": 540, "height": 960}
    assert S.reformat(s, "16:9")["recaptures"][0]["capture_id"] == "port02"


def test_reformat_rejects_unknown_aspect():
    with pytest.raises(ValueError):
        S.reformat(mk(), "1:1")


# --- layout audit --------------------------------------------------------------------------------

def box(x, y, w, h, tag="h2", text="", vis=True, clip=False):
    return {"tag": tag, "text": text, "rect": {"x": x, "y": y, "w": w, "h": h}, "vis": vis, "clip": clip}


def test_audit_flags_an_element_that_overflows_the_frame():
    fs = layout.audit_rects("16:9", (1920, 1080), [box(100, 900, 900, 400, "pre", "long code block")], "src")
    assert codes(fs) == ["outside_frame"]
    assert fs[0]["scene"] == "src" and "leaves the 1920x1080 frame" in fs[0]["message"]
    # a box that ends one pixel inside is not an overflow
    assert layout.audit_rects("16:9", (1920, 1080), [box(100, 700, 900, 380)]) == []


def test_audit_flags_the_portrait_safe_zones_only():
    els = [box(100, 400, 800, 300, "h2", "inside"),
           box(100, 1700, 800, 120, "cap", "caption under the UI"),
           box(100, 20, 800, 90, "h1", "top bar"),
           box(5, 900, 200, 100, "li", "too far left")]
    fs = layout.audit_rects("9:16", (1080, 1920), els, "s")
    assert codes(fs) == ["safe_zone", "safe_zone", "safe_zone"]
    assert {f["element"].split()[0] for f in fs} == {"cap", "h1", "li"}
    # the same boxes are fine in 16:9: it has no reserved bands
    assert layout.audit_rects("16:9", (1080, 1920), els, "s") == []


def test_audit_ignores_hidden_boxes_and_flags_clipped_content():
    assert layout.audit_rects("9:16", (1080, 1920), [box(0, 0, 10, 10, vis=False)]) == []
    assert codes(layout.audit_rects("16:9", (1920, 1080), [box(100, 100, 800, 300, "pre", clip=True)])) == \
        ["clipped_content"]


def test_audit_flags_a_focus_box_pushed_out_of_the_frame():
    fs = layout.audit_rects("9:16", (1080, 1920),
                            [{"tag": "focus", "text": "", "rect": {"x": -40, "y": 900, "w": 60, "h": 60}, "vis": True}], "ui")
    assert "focus_outside" in codes(fs)


def test_portrait_css_pads_content_past_the_safe_zones():
    portrait, wide = layout.css("9:16"), layout.css("16:9")
    assert "--pad-top:10.00%" in portrait and "--pad-bottom:30.00%" in portrait
    assert "--cap-bottom:21.00%" in portrait  # above the bottom 20% band
    assert "--cap-bottom:5.00%" in wide and "--pad-bottom:16.00%" in wide
    html = render.build_html(S.normalize({"aspect": "9:16", "scenes": [
        {"id": "a", "type": "title", "title": "Hi", "caption": "cap"}]}))
    assert "--pad-bottom:30.00%" in html and "img[data-z]{position:absolute" in html


# --- zoom --------------------------------------------------------------------------------------

def test_zoom_puts_the_focus_on_the_frame_centre():
    # capture and frame share the aspect: there is nothing to pan, so the pivot is the frame centre
    p = layout.zoom_plan(800, 450, 1280, 720, {"x": 0.05, "y": 0.05, "w": 0.2, "h": 0.2}, 1.6)
    assert (p["ox"], p["oy"]) == (0.0, 0.0)
    r = p["focus_rect"]
    assert 0 <= r["x"] and r["x"] + r["w"] <= 800 and 0 <= r["y"] and r["y"] + r["h"] <= 450
    assert r["w"] / r["h"] == pytest.approx(0.2 * 800 / (0.2 * 450))  # the crop keeps the capture's shape


def centre_after(p, focus, fw, fh, iw, ih):
    s, x0, y0 = layout.cover(fw, fh, iw, ih)
    cx = x0 + (focus["x"] + focus["w"] / 2) * iw * s
    cy = y0 + (focus["y"] + focus["h"] / 2) * ih * s
    return fw / 2 + p["z"] * (cx - fw / 2 - p["ox"]), fh / 2 + p["z"] * (cy - fh / 2 - p["oy"])


@pytest.mark.parametrize("fw,fh,iw,ih,focus,zoom", [
    (1612, 763, 1280, 720, {"x": 0.02, "y": 0.02, "w": 0.5, "h": 0.2}, 8.0),  # 16:9 capture, top-left text
    (925, 1041, 540, 960, {"x": 0.07, "y": 0.07, "w": 0.86, "h": 0.6}, 1.4),  # 9:16 capture, portrait frame
    (925, 1041, 1280, 720, {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}, 1.7),  # degenerate corner focus
    (800, 800, 2000, 2000, {"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1}, 2.0),
])
def test_zoom_plan_keeps_the_focus_visible_and_the_frame_covered(fw, fh, iw, ih, focus, zoom):
    p = layout.zoom_plan(fw, fh, iw, ih, focus, zoom)
    s, x0, y0 = layout.cover(fw, fh, iw, ih)
    dw, dh, z = iw * s, ih * s, p["z"]
    px, py = fw / 2 + p["ox"], fh / 2 + p["oy"]
    # cover cannot pan past an edge: the image still fills the frame, or a gap would show
    assert fw / 2 + z * (x0 - px) <= 1 and fw / 2 + z * (x0 + dw - px) >= fw - 1
    assert fh / 2 + z * (y0 - py) <= 1 and fh / 2 + z * (y0 + dh - py) >= fh - 1
    cx, cy = centre_after(p, focus, fw, fh, iw, ih)  # and the focus centre never leaves the frame
    assert -0.05 <= cx <= fw + 0.05 and -0.05 <= cy <= fh + 0.05
    assert p["z"] >= 1.0


def test_zoom_is_clamped_so_a_big_focus_box_stays_visible():
    p = layout.zoom_plan(1080, 1920, 1080, 1920, {"x": 0.1, "y": 0.4, "w": 0.6, "h": 0.5}, 3.0)
    assert p["zoom"] == 3.0 and p["z"] < 3.0  # the requested zoom would crop the focus box
    r = p["focus_rect"]
    assert r["w"] <= 1080 + 0.01 and r["h"] <= 1920 + 0.01 and r["x"] >= -0.01 and r["y"] >= -0.01


def test_a_centred_point_focus_zooms_freely():
    p = layout.zoom_plan(800, 800, 2000, 2000, {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}, 2.5)
    assert (p["z"], p["ox"], p["oy"]) == (2.5, 0.0, 0.0)


# --- verify -------------------------------------------------------------------------------------

def _video(path, w, h, frames=45, fps=30):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:r={fps}",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is needed to make a test video")
def test_verify_expects_1080x1920_for_portrait(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    spec = S.normalize({"aspect": "9:16", "scenes": [{"id": "a", "type": "title", "title": "Hi", "duration_s": 1.5}]})
    h = S.persist(spec)
    good, bad = tmp_path / "good.mp4", tmp_path / "bad.mp4"
    _video(good, 1080, 1920)
    _video(bad, 540, 960)
    ok = render.verify(str(good), h)
    assert "size" not in codes(ok["findings"]) and ok["expected_size"] == [1080, 1920]
    wrong = render.verify(str(bad), h)
    assert [f["message"] for f in wrong["findings"] if f["code"] == "size"] == ["540x960 != 1080x1920 for 9:16"]


# --- the audit against a real page ---------------------------------------------------------------

def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=render.ARGS, executable_path=config.chromium()).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to lay the template out")
def test_audit_flags_a_scene_that_overflows_in_the_real_template(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    spec = S.normalize({"aspect": "9:16", "scenes": [
        {"id": "t", "type": "terminal", "heading": "Too much", "duration_s": 4,
         "lines": ["$ " + "x" * 60] * 14},
        {"id": "b", "type": "bullets", "heading": "Also too much", "duration_s": 4,
         "items": ["y" * 200] * 6}]})
    h = S.persist(spec)
    a = render.audit(h)
    # the long wrapped bullets run past the bottom of the frame; only a clipping box (.term) is 'clipped'
    assert a["status"] == "warn" and a["warnings"] >= 2
    assert set(codes(a["findings"])) == {"clipped_content"}  # squeezed, not pushed out of frame
    assert {f["scene"] for f in a["findings"]} == {"t", "b"}


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to lay the template out")
def test_audit_does_not_flag_text_its_box_does_not_clip(tmp_path, monkeypatch):
    # a glyph with a descender ('_' in mint_loader) makes scrollHeight exceed clientHeight, but an
    # overflow:visible heading shows every pixel: only a clipping box can cut content off
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    spec = S.normalize({"aspect": "9:16", "scenes": [
        {"id": "title", "type": "title", "title": "mint_loader", "subtitle": "real output, staged typing",
         "duration_s": 2.5, "caption": "one spec, every format"},
        {"id": "t", "type": "terminal", "heading": "in a real shell", "duration_s": 4,
         "lines": ["$ mint_loader /bin/echo mint-loader-ok", "mint-loader-ok", "$ "]}]})
    h = S.persist(spec)
    a = render.audit(h)
    assert (a["status"], a["warnings"], a["findings"]) == ("ok", 0, [])
    assert len(render.stills(h)) == 2 and render.stills_done(h)
