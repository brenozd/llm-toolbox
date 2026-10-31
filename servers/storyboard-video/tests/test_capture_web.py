"""capture_web against a real page: the `focus` box has to describe the pixels in the PNG, a
selector that never matches must be a finding instead of a 30 s traceback, and a page that cannot be
loaded must come back as an error dict (U2a, U2b, A1b)."""
import functools
import http.server
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from storyboard_video_mcp import capture, config, render


def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=render.ARGS, executable_path=config.chromium()).close()
        return True
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not _chromium(), reason="chromium is needed to capture a page")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg is needed to read the PNG back")

PAGE = """<!doctype html><html><body style="margin:0;height:4000px;background:#ffffff">
<div id="target" style="position:absolute;top:3000px;left:0;width:100%;height:120px;background:#ff0000">
</div></body></html>"""

# a second page of the same app, unmistakable at the pixel level: goto_path has to land on it
SECOND = """<!doctype html><html><body style="margin:0;height:800px;background:#ff00ff"></body></html>"""

# a page that shows #ready only after a tick (an SSE/streaming app painting late)
LATE = """<!doctype html><html><body style="margin:0;height:800px;background:#ffffff">
<script>setTimeout(function(){var d=document.createElement('div');d.id='ready';d.textContent='ready';
d.style.cssText='width:200px;height:80px;background:#00ff00';document.body.appendChild(d);},300);</script>
</body></html>"""


@pytest.fixture()
def page_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path / "work")
    docroot = tmp_path / "www"
    docroot.mkdir()
    (docroot / "index.html").write_text(PAGE)
    (docroot / "second.html").write_text(SECOND)
    (docroot / "late.html").write_text(LATE)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(docroot))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    finally:
        srv.shutdown()


def _png_rgb(path: Path) -> tuple[int, int, bytes]:
    """Decode the PNG to raw RGB8: (width, height, pixels). ffmpeg only, no imaging library."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    w, h = (int(v) for v in probe.stdout.strip().split(","))
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    assert len(raw) == w * h * 3
    return w, h, raw


def _center_rgb(path: Path) -> tuple[int, int, int]:
    """The pixel in the middle of the shot: which page got captured, without a diff."""
    w, h, raw = _png_rgb(path)
    i = ((h // 2) * w + w // 2) * 3
    return tuple(raw[i:i + 3])


@needs_browser
@needs_ffmpeg
def test_focus_names_the_pixels_that_are_in_the_png(page_url):
    """The box used to be measured after the shot, so it described a region the PNG did not have:
    a wrong zoom in every scrolled capture. Ask for an element 3000 px down the page and check the
    accent colour really sits where `focus` says."""
    res = capture.capture_web(page_url, [{"id": "accent", "selector": "#target"}], aspect="9:16")
    assert res["status"] == "ok", res
    shot = res["shots"][0]
    f = shot["focus"]
    assert f and all(0.0 <= f[k] <= 1.0 for k in ("x", "y", "w", "h")), f
    w, h, raw = _png_rgb(Path(shot["path"]))
    x0, x1 = int(f["x"] * w), int((f["x"] + f["w"]) * w)
    y0, y1 = int(f["y"] * h), int((f["y"] + f["h"]) * h)
    assert x1 > x0 and y1 > y0
    red = 0
    for y in range(y0, y1):
        row = raw[(y * w + x0) * 3:(y * w + x1) * 3]
        red += sum(1 for i in range(0, len(row), 3) if row[i] > 180 and row[i + 1] < 80 and row[i + 2] < 80)
    band = (x1 - x0) * (y1 - y0)
    assert red > 0.5 * band, f"{red} accent pixels of {band}: the focus box does not describe the shot"


@needs_browser
def test_a_selector_that_never_matches_is_a_finding_not_a_lost_take(page_url):
    """bounding_box() used to have no timeout: a selector matching nothing raised Playwright's
    TimeoutError after 30 s and threw away every shot of the call."""
    t = time.monotonic()
    res = capture.capture_web(page_url, [{"id": "missing", "selector": "#nope"}, {"id": "plain"}], aspect="16:9")
    elapsed = time.monotonic() - t
    assert res["status"] == "ok", res
    first, second = res["shots"]
    assert first["focus"] is None and first["selector_missing"] == "#nope"
    assert Path(first["path"]).exists()  # the shot is still taken, just without a zoom
    assert second["focus"] is None and "selector_missing" not in second
    assert elapsed < 10, f"a missing selector must fail fast, took {elapsed:.1f}s"


@needs_browser
def test_a_page_that_cannot_be_loaded_is_an_error_receipt(page_url, tmp_path):
    """A refused connection is a finding (error dict), not an exception escaping the tool."""
    res = capture.capture_web("http://127.0.0.1:1/index.html", [{"id": "a"}], aspect="16:9")
    assert res["status"] == "error" and "could not load" in res["message"], res


@needs_browser
def test_a_shot_without_a_usable_id_is_an_error_receipt(page_url):
    """shots[0]["id"] used to raise a KeyError out of the tool: a shot names its own PNG, so a missing
    (or blank) id is a finding the caller can act on."""
    res = capture.capture_web(page_url, [{"selector": "#target"}])
    assert res["status"] == "error" and "'id'" in res["message"] and "shots[0]" in res["message"], res
    res = capture.capture_web(page_url, [{"id": "ok"}, {"id": "   "}])
    assert res["status"] == "error" and "shots[1]" in res["message"], res


@needs_browser
def test_an_output_png_is_rejected_instead_of_navigated_to(page_url):
    """`path` is the URL path of the page to open, but callers passed the PNG they wanted and the tool
    silently navigated to a file. Both names are now checked, per shot, before anything is opened."""
    res = capture.capture_web(page_url, [{"id": "ext", "goto_path": "/captures/dash.png"},
                                         {"id": "alias", "path": "out/receipt.jpeg"},
                                         {"id": "cnt", "goto_path": "/work/dashboard"},
                                         {"id": "tmp", "goto_path": "/tmp/page"},
                                         {"id": "good"}], aspect="16:9")
    assert res["status"] == "ok", res
    ext, alias, cnt, tmp, good = res["shots"]
    for s in (ext, alias, cnt, tmp):
        assert s["path"] is None and s["focus"] is None, s
        assert "shots[].path" in s["message"], s  # the message names the field that carries the PNG
    assert "output image" in ext["message"] and "output image" in alias["message"], (ext, alias)
    assert "container path" in cnt["message"] and "container path" in tmp["message"], (cnt, tmp)
    assert Path(good["path"]).exists()  # the valid shot of the same call still ships


@needs_browser
@needs_ffmpeg
def test_goto_path_opens_the_page_the_shot_names_and_path_still_works(page_url):
    """The renamed field has to navigate, its old alias has to keep working, and the PNG has to be of
    the page the shot named (magenta), not of the url passed to the call (white)."""
    res = capture.capture_web(page_url, [{"id": "home"}, {"id": "magenta", "goto_path": "/second.html"},
                                         {"id": "alias", "path": "/second.html"}], aspect="16:9")
    assert res["status"] == "ok", res
    home, mag, alias = res["shots"]
    assert "goto_path" not in home
    assert mag["goto_path"] == alias["goto_path"] == "/second.html"
    assert _center_rgb(Path(mag["path"])) == (255, 0, 255), mag
    assert _center_rgb(Path(alias["path"])) == (255, 0, 255), alias
    assert _center_rgb(Path(home["path"])) != (255, 0, 255), home


@needs_browser
def test_wait_for_is_bounded_and_a_missing_one_is_a_finding_not_a_lost_take(page_url):
    """An SSE/late page needs a real signal to shoot on: `wait_for` waits for the selector as visible and,
    when it never appears, records `wait_missing` and still takes the shot (bounded, no 30 s hang)."""
    t = time.monotonic()
    res = capture.capture_web(page_url, [{"id": "late", "goto_path": "/late.html", "wait_for": "#ready"},
                                         {"id": "missing", "goto_path": "/late.html", "wait_for": "#nope"}],
                              aspect="16:9")
    elapsed = time.monotonic() - t
    assert res["status"] == "ok", res
    late, missing = res["shots"]
    assert "wait_missing" not in late and Path(late["path"]).exists(), late
    assert missing["wait_missing"] == "#nope" and Path(missing["path"]).exists(), missing
    assert elapsed < 15, f"the wait must be bounded, took {elapsed:.1f}s"


@needs_browser
def test_settle_ms_waits_before_the_shot_and_a_bad_value_is_a_finding(page_url):
    """`settle_ms` is the paint budget after navigation+wait; a value outside 0..10000 is rejected per
    shot instead of silently ignored."""
    t = time.monotonic()
    res = capture.capture_web(page_url, [{"id": "settled", "goto_path": "/second.html", "settle_ms": 400},
                                         {"id": "toobig", "settle_ms": 20000},
                                         {"id": "text", "settle_ms": "200"}], aspect="16:9")
    elapsed = time.monotonic() - t
    assert res["status"] == "ok", res
    settled, toobig, text = res["shots"]
    assert Path(settled["path"]).exists(), settled
    assert elapsed >= 0.4, f"settle_ms was not spent, took {elapsed:.2f}s"
    for s in (toobig, text):
        assert s["path"] is None and "settle_ms must be an integer 0..10000" in s["message"], s


def test_a_null_goto_path_falls_back_to_the_path_alias():
    assert capture._goto_path({"goto_path": None, "path": "/a"}) == "/a"
    assert capture._goto_path({"goto_path": "/b", "path": "/a"}) == "/b"
    assert capture._goto_path({"goto_path": ""}) is None
