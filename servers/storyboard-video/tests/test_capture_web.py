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


@pytest.fixture()
def page_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path / "work")
    docroot = tmp_path / "www"
    docroot.mkdir()
    (docroot / "index.html").write_text(PAGE)
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
