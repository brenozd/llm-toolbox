"""The template itself: motion is one constant the frame loop obeys, and align belongs to the scene.

The complaint this file defends against: on-screen text kept scaling up for the whole scene, so a
card looked like it was still growing seconds after it entered. `subtle` settles in 0.8 s and holds;
`lively` is the old behaviour; `still` never moves the frame."""

import time

import pytest

from storyboard_video_mcp import config, render, spec as S


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi", "duration_s": 4}], **kw})


def test_build_html_carries_the_motion_constant_and_an_fps_settle():
    html = render.build_html(mk(direction={"motion": "still"}))
    assert 'M="still"' in html and "Math.round(F*0.8)" in html and "F=30" in html
    assert 'M="subtle"' in render.build_html(mk())  # the default that fixes the complaint
    assert 'F=60' in render.build_html(mk(fps=60))  # the settle is seconds, not frames: 60 fps must still settle


def test_align_left_takes_the_centring_off_a_title():
    assert 'class="c center"><h1' in render.build_html(mk())
    left = render.build_html(mk(direction={"scenes": {"a": {"align": "left"}}}))
    assert 'class="c"><h1' in left and 'class="c center"><h1' not in left


def test_panel_and_line_are_mixed_from_the_theme():
    """A light user palette must still see the window frames: white-on-white came from hardcoded hexes."""
    html = render.build_html(mk(theme={"bg": "#ffffff", "fg": "#000000"}))
    assert "--panel:#f0f0f0" in html and "--line:#d1d1d1" in html


def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=render.ARGS, executable_path=config.chromium()).close()
        return True
    except Exception:
        return False


def _frames(spec: dict, frames: list[int]) -> list[bytes]:
    """The same scene shot at several frames through the real template."""
    h = S.persist(spec)
    with render.sync_playwright() as p:
        br, ctx = render._open(p, spec, 0.5)
        pg, _ = render._page(ctx, spec, h)
        shots = []
        for f in frames:
            pg.evaluate(f"seek({f})")
            shots.append(pg.screenshot(type="png"))
        br.close()
    return shots


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to shoot the template")
def test_text_stops_moving_after_it_entered(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    # 4 s at 30 fps: frames 40 and 100 are both mid-scene, long past the entrance animation
    settled = _frames(mk(), [40, 100])
    assert settled[0] == settled[1], "subtle must settle: the card is pixel-identical at frame 40 and 100"
    growing = _frames(mk(motion="lively"), [40, 100])
    assert growing[0] != growing[1], "lively is the old always-growing scale and must still differ"


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to shoot the template")
def test_still_never_scales_the_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    shots = _frames(mk(motion="still", direction={"motion": "still"}), [18, 60])
    assert shots[0] == shots[1]


@pytest.mark.skipif(not _chromium(), reason="chromium is needed to shoot the template")
def test_stills_spot_check_a_moment_and_the_digest_proves_the_card_held(tmp_path, monkeypatch):
    """The Done-when "same pixels mid-scene" check has to be runnable with the tool surface."""
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    h = S.persist(mk())
    early, late = render.stills(h, 1.5), render.stills(h, 2.5)  # 4 s scene: both past the 0.8 s settle
    assert early[0]["digest"] == late[0]["digest"]
    assert render.stills(h, 0.2)[0]["digest"] != early[0]["digest"]  # the entrance is real, the growth is not
    assert not render.stills_done(h)  # a spot-check is not the review set
    render.stills(h)
    assert render.stills_done(h)


def test_render_status_reports_elapsed_seconds_and_keeps_the_other_keys(monkeypatch):
    """A background job used to report progress only: a render at 5% for two minutes looked identical to
    a stuck one. `elapsed_s` says how long it has been running and freezes when it ends."""
    jid = "t000elap"
    monkeypatch.setitem(render.JOBS, jid, {"status": "running", "progress": 0.25,
                                           "started_at": time.time() - 4.0})
    st = render.status(jid)
    assert st["status"] == "running" and st["progress"] == 0.25
    assert 3.9 <= st["elapsed_s"] < 6.0, st["elapsed_s"]
    render.JOBS[jid].update(status="done", finished_at=time.time())
    frozen = render.status(jid)["elapsed_s"]
    time.sleep(0.2)
    assert render.status(jid)["elapsed_s"] == frozen, "a finished job must not keep counting"
    assert render.status("nope") == {"status": "error", "message": "unknown job_id"}
    assert render.status(jid) is not render.JOBS[jid]  # a snapshot: a caller cannot mutate the job


def test_a_started_job_stamps_its_start_and_stops_the_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(render, "render_sync", lambda h, q, job: {"video": "x.mp4"})
    jid = render.start(S.persist(mk()), "draft")
    job = render.JOBS[jid]
    assert isinstance(job["started_at"], float) and job["started_at"] > 0
    for _ in range(100):  # a real thread: wait for it instead of assuming it ran
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    st = render.status(jid)
    assert st["result"] == {"video": "x.mp4"} and "finished_at" in st and st["elapsed_s"] >= 0
