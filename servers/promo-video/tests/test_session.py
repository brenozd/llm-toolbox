import json
import random
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from promo_video_mcp import capture, config, render, spec as S


def test_session_steps_are_validated_and_defaulted():
    steps = capture._norm_steps([{"type": "type", "text": "ls"}, {"type": "key", "key": "Return"},
                                 {"type": "hold_s"}, {"type": "wait_for", "text": "$ "}])
    assert [s["type"] for s in steps] == ["type", "key", "hold_s", "wait_for"]
    assert steps[2]["s"] == 0.5 and steps[3]["timeout_s"] == 8.0
    for bad in ([], [{"type": "nope"}], [{"type": "type"}], [{"type": "wait_for", "text": ""}], [{"type": "key"}]):
        with pytest.raises(ValueError):
            capture._norm_steps(bad)


def test_session_needs_exec(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_EXEC", False)
    with pytest.raises(PermissionError):
        capture.capture_terminal_session([{"type": "key", "key": "Return"}])


def test_vmap_plays_at_clip_speed_then_freezes_the_last_frame():
    assert render._vmap(3, 6, 15, 30) == [0, 0, 1, 1, 2, 2]  # half the scene fps: each clip frame twice
    assert render._vmap(3, 10, 15, 30)[-4:] == [2, 2, 2, 2]  # scene longer than the clip: tail frozen
    assert render._vmap(60, 300, 15, 30)[-1] == 59  # never past the last extracted frame
    assert render._vmap(0, 3, 15, 30) == []


def test_terminal_scene_accepts_a_video(tmp_path):
    vid = tmp_path / "session.mp4"
    vid.write_bytes(b"\0" * 2048)  # lint only checks that the path exists
    s = S.normalize({"scenes": [{"id": "t", "type": "terminal", "video": str(vid)}]})
    assert not [f for f in S.lint(s) if f["severity"] == "error"]


def test_lint_warns_when_the_scene_cuts_before_the_output_holds(tmp_path, monkeypatch):
    """The last line of a real take has to stay on screen: duration_s must cover typing + 4 s."""
    monkeypatch.setattr(config, "WORK", tmp_path)
    d = tmp_path / "captures" / "abc12345"
    d.mkdir(parents=True)
    (d / "capture.json").write_text(json.dumps({"tool": "capture_terminal_session", "aspect": "16:9",
                                                "typing_end_s": 3.0}))
    vid = d / "session.mp4"
    vid.write_bytes(b"\0" * 2048)
    s = S.normalize({"scenes": [{"id": "t", "type": "terminal", "video": str(vid), "duration_s": 5}]})
    assert "short_hold" in {f["code"] for f in S.lint(s)}
    s["scenes"][0]["duration_s"] = 7  # typing_end_s + MIN_HOLD_S
    assert "short_hold" not in {f["code"] for f in S.lint(s)}


def test_terminal_recording_is_scaled_to_the_content_box():
    plain = render._box_scale(1920, 1080, "16:9", False, 1056, 634)
    assert 1.0 < plain <= 1.35  # a 16 px recording must not stay a stamp in a 1080p frame
    assert render._box_scale(1920, 1080, "16:9", True, 1056, 634) < plain  # the heading costs height
    assert render._box_scale(0, 0, "16:9", False, 1056, 634) == 1.0


def test_default_session_geometry_fills_the_frame_width():
    """The default 16:9/9:16 grids were picked so a take is not a stamp in the middle of the frame:
    window sizes measured with xdotool in the image (1444x633 = 80x16 at font 22)."""
    s = render._box_scale(1920, 1080, "16:9", False, 1444, 633)
    assert 1444 * s >= 0.8 * 1920 and 633 * s >= 0.55 * 1080  # no heading: width-bound
    sh = render._box_scale(1920, 1080, "16:9", True, 1444, 633)  # with a heading it is height-bound
    assert 1444 * sh >= 0.75 * 1920
    p = render._box_scale(1080, 1920, "9:16", False, 576, 706)  # 44x28 at font 15
    assert 576 * p >= 0.8 * 1080


def test_display_claims_are_atomic_and_released(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "LOCKDIR", tmp_path)
    (tmp_path / ".X90-lock").write_text("")  # somebody else's server: never hand out :90
    a, lock_a = capture._claim_display()
    b, lock_b = capture._claim_display()
    assert (a, b) == (":91", ":92") and lock_a.exists() and lock_b.exists()
    lock_a.unlink()
    assert capture._claim_display() == (a, lock_a)  # a released display is claimed again


def test_concurrent_display_claims_never_collide(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "LOCKDIR", tmp_path)
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(lambda _: capture._claim_display()[0], range(4)))
    assert len(set(got)) == 4


def test_window_search_finds_only_our_own_take():
    ours, theirs = "terminal ab12cd34", "terminal ab12cd35"  # two takes, two displays
    rx = re.compile(capture._win_search(ours)[-1])
    assert rx.match(ours) and not rx.match(theirs) and not rx.match(ours + " 2")


def test_xterm_focuses_the_window_matching_its_unique_title(monkeypatch, tmp_path):
    names = ["terminal ab12cd34", "terminal ab12cd35"]

    def run(env, argv, timeout=15):
        if argv[1] == "search":
            hits = [n for n in names if re.match(argv[-1], n)]
            return subprocess.CompletedProcess(argv, 0 if hits else 1, "\n".join(["7"] * len(hits)), "")
        if argv[1] == "getwindowgeometry":
            return subprocess.CompletedProcess(argv, 0, "WINDOW=7\nX=0\nY=0\nWIDTH=800\nHEIGHT=600\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(capture, "_run", run)
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **k: object())
    _, win, geo = capture._xterm({}, tmp_path, 80, 24, 14, "terminal ab12cd34", tmp_path / "log", tmp_path / "rc")
    assert win == "7" and geo == (0, 0, 800, 600)


def test_xdotool_failures_are_raised_not_ignored(monkeypatch):
    monkeypatch.setattr(capture, "_run", lambda env, argv, timeout=15:
                        subprocess.CompletedProcess(argv, 1, "", "Failed to get window geometry"))
    with pytest.raises(capture._XdoError, match="getwindowgeometry"):
        capture._xdo({}, ["getwindowgeometry", "--shell", "7"], "getwindowgeometry")


def test_typing_fails_loudly_on_a_char_xdotool_cannot_send(monkeypatch):
    typed = []

    def fake(env, argv, what):
        if argv[-1] == "€":
            raise capture._XdoError("xdotool type '€' failed (rc=1)")
        typed.append(argv[-1])
        return ""

    monkeypatch.setattr(capture, "_xdo", fake)
    with pytest.raises(capture._XdoError):
        capture._type_text({}, "ls €", 0, 0, random.Random(0))
    assert typed == ["l", "s", " "]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed to make and read a test capture")
def test_sparse_capture_warns_on_a_mostly_black_image(tmp_path):
    black, busy, white = tmp_path / "black.png", tmp_path / "busy.png", tmp_path / "white.png"
    for out, src in ((black, "color=c=black:s=320x180"), (busy, "testsrc=s=320x180"), (white, "color=c=white:s=320x180")):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-frames:v", "1", str(out)],
                       check=True)
    s = S.normalize({"scenes": [{"id": "a", "type": "image", "image": str(black)},
                                {"id": "b", "type": "image", "image": str(busy)},
                                {"id": "c", "type": "image", "image": str(white)}]})
    assert [f["scene"] for f in S.lint(s) if f["code"] == "sparse_capture"] == ["a", "c"]


def test_tail_hides_the_setup_output_from_the_receipt(tmp_path):
    """`setup` runs before the grab: its output (and `clear`) must not reach the returned `lines`,
    which are what the video shows."""
    log = tmp_path / "pty.log"
    setup = b"Script started on x\r\n/work/leak.c:12: warning: unused variable\r\n"
    log.write_bytes(setup + b"$ mint_loader ./leak\r\nleaked 42 bytes\r\n$ ")
    assert capture._tail(log, off=len(setup)).splitlines() == ["$ mint_loader ./leak", "leaked 42 bytes", "$ "]
    assert "/work" in capture._tail(log)  # the log itself still has it: only the receipt is trimmed


def test_session_setup_must_be_a_string(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_EXEC", True)
    with pytest.raises(ValueError, match="setup"):
        capture.capture_terminal_session([{"type": "key", "key": "Return"}], setup=["cd /tmp"])
