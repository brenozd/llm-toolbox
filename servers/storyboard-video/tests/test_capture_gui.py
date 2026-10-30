"""capture_gui on a real X display: the screen has to be the aspect's size, the shot has to contain
the app's pixels, and the display must come from the shared, readiness-polled `_xvfb` helper instead
of a re-implemented Xvfb with a fixed sleep (U3)."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from storyboard_video_mcp import capture, config

needs_gui = pytest.mark.skipif(
    not all(shutil.which(n) for n in ("Xvfb", "ffmpeg", "ffprobe", "xmessage", "xdpyinfo")),
    reason="Xvfb + ffmpeg + xmessage are needed to shoot a GUI")


def _ink_fraction(path) -> float:
    """Share of pixels that are not near-black: an empty root window gives ~0."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    w, h = (int(v) for v in probe.stdout.strip().split(","))
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    lit = sum(1 for i in range(0, len(raw), 3) if max(raw[i], raw[i + 1], raw[i + 2]) > 60)
    return lit / (w * h)


@needs_gui
def test_gui_capture_shoots_the_app_at_the_aspect_size(tmp_path, monkeypatch):
    """The container ships no GTK/Qt, so xmessage (x11-utils) is the GUI app the image can run."""
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    res = capture.capture_gui("xmessage -geometry 700x400 hi", aspect="9:16", seconds=2.0)
    assert res["status"] == "ok", res
    assert res["app_alive"] is True and res["size"] == "720x1280"
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", res["path"]], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "720,1280"
    assert _ink_fraction(res["path"]) > 0.005, "the screenshot is an empty X root window"  # ~30% with that window


@needs_gui
def test_gui_capture_kills_the_app_and_frees_the_display(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    monkeypatch.setattr(capture, "LOCKDIR", tmp_path)
    res = capture.capture_gui("xmessage -center bye", aspect="16:9", seconds=1.0)
    assert res["status"] == "ok", res
    assert not list(tmp_path.glob(".storyboard-x*.lock")), "the display claim was not released"


def test_gui_capture_uses_the_shared_xvfb_helper(tmp_path, monkeypatch):
    """U3: one Xvfb launcher for the whole module (readiness-polled), not a second copy with sleep(1)."""
    seen = {}

    def fake_xvfb(env, disp, w, h):
        seen.update(env=env, disp=disp, w=w, h=h)
        return SimpleNamespace(pid=0)

    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    monkeypatch.setattr(capture, "_claim_display", lambda: (":97", tmp_path / ".storyboard-x97.lock"))
    monkeypatch.setattr(capture, "_xvfb", fake_xvfb)
    monkeypatch.setattr(capture.shutil, "which", lambda n: "/usr/bin/" + n)  # CI image has no Xvfb/ffmpeg
    monkeypatch.setattr(capture, "_kill", lambda p: seen.setdefault("killed", True))
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=0, poll=lambda: 0))
    monkeypatch.setattr(capture.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    res = capture.capture_gui("true", aspect="9:16")
    assert seen["w"] == 720 and seen["h"] == 1280 and seen["disp"] == ":97"
    assert seen["env"]["DISPLAY"] == ":97"  # the helper's readiness probe talks to *our* display
    assert seen["killed"] is True  # the fake server is stopped on the way out
    assert res["status"] == "warn"  # the app exited before the shot: said so, did not fail
    assert "exited before the screenshot" in res["note"]


def test_gui_capture_rejects_a_size_that_is_not_widthxheight(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    res = capture.capture_gui("true", size="720by1280")
    assert res["status"] == "error" and "WIDTHxHEIGHT" in res["message"]
