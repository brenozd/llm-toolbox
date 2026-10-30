"""The whole render, not a piece of it: the real template, real ffmpeg, a real MP4 handed back to
`verify`. Two verify bars are exercised here because they used to judge the wrong frame/stream:

- a 9:16 delivery was never rendered by a test at all (only synthetic 1080x1920 mp4s were verified);
- `blank_frame` sampled one frame per checkpoint, so a scene's entrance frame (opacity 0) or a crossfade
  tail -- legitimately black -- was reported as a blank video;
- `unexpected_audio` warned about the music bed the render itself had mixed in.
"""

import os
import shutil
import subprocess

import pytest

from storyboard_video_mcp import config, render, spec as S


def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=render.ARGS, executable_path=config.chromium()).close()
        return True
    except Exception:
        return False


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    return tmp_path


def codes(findings):
    return {f["code"] for f in findings}


def mk(**kw):
    return S.normalize({"fps": 10, "scenes": [
        {"id": "t", "type": "title", "title": "Portrait", "subtitle": "9:16", "duration_s": 2},
        {"id": "b", "type": "bullets", "heading": "Two", "items": ["one", "two"], "duration_s": 2}], **kw})


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to render the template")
def test_a_portrait_delivery_renders_and_verifies_clean(work):
    """9:16 end to end: stills (the delivery gate), the delivery render, and the file verify reads back."""
    h = S.persist(mk(aspect="9:16"))
    render.stills(h)
    rec = render.render_sync(h, "delivery", {})
    assert (rec["width"], rec["height"]) == (1080, 1920)  # the delivery frame of a portrait spec
    v = render.verify(rec["video"], h)
    assert v["expected_size"] == [1080, 1920] and v["probe"]["height"] == 1920
    assert v["findings"] == [] and v["status"] == "ok"


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to render the template")
def test_verify_is_not_fooled_by_an_entrance_frame(work):
    """Two 1.5 s scenes at 10 fps, a 0.4 s transition: the 50 % checkpoint (1.3 s) lands exactly on the
    crossfade midpoint, where the outgoing scene has faded out and the incoming one has not started
    (opacity 0 both, variance 0.13). One sampled frame called that a blank video; the window finds the
    picture a quarter of a second either side."""
    h = S.persist(S.normalize({"fps": 10, "transition_s": 0.4, "scenes": [
        {"id": "a", "type": "title", "title": "First", "duration_s": 1.5},
        {"id": "b", "type": "title", "title": "Second", "duration_s": 1.5}]}))
    rec = render.render_sync(h, "draft", {})
    total = S.timeline(S.load(h))["frames"] / 10
    mid = total * 0.5
    # the dark frame is real: this is what used to be reported, and it is not a broken render
    assert min(render._var(rec["video"], mid + d) for d in (-0.25, 0.0, 0.25)) < render.BLANK_VAR
    v = render.verify(rec["video"], h)
    assert "blank_frame" not in codes(v["findings"]), v["findings"]
    assert v["status"] == "ok"


@pytest.mark.skipif(not _chromium() or not shutil.which("ffmpeg"),
                    reason="chromium and ffmpeg are needed to mix a bed")
def test_a_music_bed_is_not_unexpected_audio(work):
    """A silent spec with a music bed carries an audio stream on purpose: the receipt names the track, so
    verify must report the audio (and its loudness) instead of warning about it."""
    track = work / "music" / "bed.wav"
    track.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:sample_rate=48000:duration=4", str(track)], check=True)
    h = S.persist(mk(music={"path": str(track), "license": "CC0 1.0"}))
    rec = render.render_sync(h, "draft", {})
    assert rec["mix"]["music"] == str(track) and rec["mix"]["voice"] is False
    v = render.verify(rec["video"], h)
    assert v["audio"] is not None and v["narrated"] is False
    assert "unexpected_audio" not in codes(v["findings"]), v["findings"]
    assert v["loudness"]["integrated_lufs"] is not None


def _clip(work, name):
    out = work / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=320x180:r=10",
                    "-pix_fmt", "yuv420p" if name.endswith("mp4") else "rgb8", str(out)], check=True)
    return str(out)


def test_an_image_scene_takes_a_clip_instead_of_a_still(work):
    sp = S.normalize({"fps": 10, "scenes": [{"id": "c", "type": "image", "video": "x.mp4", "duration_s": 2}]})
    assert "missing_field" not in codes(S.lint(sp))
    sp = S.normalize({"fps": 10, "scenes": [{"id": "c", "type": "image", "duration_s": 2}]})
    assert "missing_field" in codes(S.lint(sp))  # neither still nor clip


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to render the template")
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed")
@pytest.mark.parametrize("name", ["clip.mp4", "clip.gif"])
def test_an_image_scene_renders_a_clip(work, name):
    clip = _clip(work, name)
    sp = S.normalize({"fps": 10, "scenes": [{"id": "c", "type": "image", "video": clip, "duration_s": 2,
                                             "heading": "Live", "focus": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}}]})
    h = S.persist(sp)
    rec = render.render_sync(h, "draft", {})
    v = render.verify(rec["video"], h)
    assert v["status"] == "ok", v["findings"]
    assert render._var(rec["video"], 0.3) > render.BLANK_VAR  # not blank, with the focus zoom applied


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to render the template")
def test_stills_follow_a_clip_through_time(work):
    """A clip scene is not frozen on its first frame: two moments give two different stills."""
    clip = _clip(work, "clip.mp4")
    sp = S.normalize({"fps": 10, "scenes": [{"id": "c", "type": "image", "video": clip, "duration_s": 2,
                                             "focus": {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}}]})
    h = S.persist(sp)
    a, b = (render.stills(h, t)[0]["digest"] for t in (0.1, 1.5))
    assert a != b


def test_clip_frames_are_jpeg_for_video_and_png_for_gif(work):
    mp4, gif = _clip(work, "c.mp4"), _clip(work, "c.gif")
    assert render.clip_frames(mp4, 5, 10)[0].endswith(".jpg")
    assert render.clip_frames(gif, 5, 10)[0].endswith(".png")
    assert render._img_uri(render.clip_frames(mp4, 1, 10)[0]).startswith("data:image/jpeg;base64,")


def test_old_frame_dirs_are_evicted_but_not_the_current_one(work):
    root = config.WORK / "frames"
    root.mkdir(parents=True, exist_ok=True)
    old = []
    for i in range(10):
        d = root / f"old{i}"
        d.mkdir()
        os.utime(d, (1, 1 + i))
        old.append(d)
    render.clip_frames(_clip(work, "c.mp4"), 3, 10)
    assert sum(d.exists() for d in old) <= 8  # the newest few stay, the ancient ones go
