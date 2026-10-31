import json

import pytest

from storyboard_video_mcp import audio as A, config, render as R, spec as S

BY = {"license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
      "title": "Slow Ambient", "creator": "Someone",
      "attribution": "Slow Ambient by Someone, CC BY 4.0, changes: trimmed to 20 s"}


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def codes(s):
    return {f["code"] for f in S.lint(s)} - {"no_direction"}  # every spec without a direction warns; not what this test is about


def staged(work, name="track.mp3"):
    p = work / "music" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0")
    return str(p)


def test_verdict_comes_from_the_licence_alone():
    assert S.music_verdict("CC0 1.0") == "allow"
    assert S.music_verdict("PDM") == "allow"
    assert S.music_verdict("Public domain") == "allow"
    assert S.music_verdict("CC BY 4.0") == "attribution"
    assert S.music_verdict("CC BY-SA 4.0") == "deny"
    assert S.music_verdict("CC BY-NC 4.0") == "deny"
    assert S.music_verdict("CC BY-ND 4.0") == "deny"
    assert S.music_verdict("") == "deny"
    # the gate is an allow-list: anything it does not recognise must not ride along uncredited
    for lic in ("All rights reserved", "proprietary", "Attribution-ShareAlike", "royalty-free?"):
        assert S.music_verdict(lic) == "deny", lic


def test_a_staged_cc0_track_lints_clean(work):
    s = mk(music={"path": staged(work), "license": "CC0 1.0"})
    assert codes(s) == set()


def test_a_missing_file_or_licence_is_an_error(work):
    assert "music_path_missing" in codes(mk(music={"path": "/music/nope.mp3", "license": "CC0 1.0"}))
    assert "music_path_missing" in codes(mk(music={"path": "/etc/passwd", "license": "CC0 1.0"}))
    assert "music_license_missing" in codes(mk(music={"path": staged(work)}))
    assert "bad_music" in codes(mk(music="chill-main-menu.mp3"))  # not an object at all


def test_a_cc_by_track_needs_its_attribution(work):
    s = mk(music={"path": staged(work), "license": "CC BY 4.0", "title": "X"})
    assert codes(s) == {"music_license_missing"}  # a BY track with an empty attribution
    assert codes(mk(music={"path": staged(work), "license": "CC BY 4.0", **BY})) == set()
    assert codes(mk(music={"path": staged(work), "license": "CC BY 4.0",
                           "attribution": "X by Y, CC BY 4.0, changes: trimmed"})) == {
        "music_license_missing"}  # a credit with no licence link is not a credit
    assert codes(mk(music={"path": staged(work), "license": "CC BY 4.0",
                           "attribution": f"X by Y, {BY['license_url']}, changes: trimmed"})) == set()


def test_start_s_must_be_a_number_of_seconds(work):
    for bad in ("abc", -5, float("nan"), True):
        assert "bad_music_start" in codes(mk(music={"path": staged(work), "license": "CC0 1.0", "start_s": bad})), bad
    assert codes(mk(music={"path": staged(work), "license": "CC0 1.0", "start_s": 0})) == set()


def test_incompatible_licences_are_rejected(work):
    for lic in ("CC BY-SA 4.0", "CC BY-NC 4.0", "CC BY-ND 4.0"):
        assert codes(mk(music={"path": staged(work), "license": lic, "attribution": "x"})) == {
            "music_license_incompatible"}, lic


def test_the_bed_reads_the_path_and_starts_at_start_s(work):
    s = mk(music={"path": staged(work), "license": "CC0 1.0", "start_s": 3.2})
    p, levels = A.bed(s)
    assert p.is_file() and levels["start_s"] == 3.2
    assert "atrim=start=3.200:end=15.200" in A.mix_graph(12.0, False, True, -18.0, 12.0, 3.2)
    assert A.bed(mk(music={"path": "/music/gone.mp3", "license": "CC0 1.0"})) is None
    assert A.bed(mk()) is None  # no music: a silent video, not an error


def test_credits_block_carries_the_licence_and_the_attribution():
    text = A.credits_text(mk(music={"path": "/music/t.mp3", **BY}))
    assert "Slow Ambient by Someone" in text and BY["license_url"] in text
    assert BY["attribution"] in text and "changes:" in text
    assert A.credits_text(mk()) is None
    cc0 = A.credits_text(mk(music={"path": "/music/t.mp3", "license": "CC0 1.0", "title": "T"}))
    assert "CC0 1.0" in cc0  # a credit block is written even when none is required
    # the loudness line is opt-in: CREDITS.txt is written before verify measures the delivery, so the
    # block only states the target when whoever writes it knows it
    assert "LUFS" not in text
    assert "- Audio mastered to -14 LUFS integrated" in A.credits_text(mk(music={"path": "/music/t.mp3", **BY}), -14)
    assert "- Audio mastered to -16 LUFS integrated" in A.credits_text(
        mk(music={"path": "/music/t.mp3", **BY}), -16.0)
    with pytest.raises(ValueError):
        A.credits_text(mk(music={"path": "/music/t.mp3", **BY}), -30)


def test_write_credits_never_leaves_a_stale_block(work):
    out = work / "out" / "abc123"
    assert A.write_credits(mk(music={"path": "/music/t.mp3", **BY}), out) == str(work / "CREDITS.txt")
    assert "Someone" in (work / "CREDITS.txt").read_text()
    assert "Someone" in (out / "CREDITS.txt").read_text()  # the copy next to the video survives a re-render
    assert A.write_credits(mk(), out) is None
    assert not (work / "CREDITS.txt").exists()  # the previous video's credit is gone
    assert not (out / "CREDITS.txt").exists()


def test_verify_reports_a_missing_credit(work):
    s = mk(aspect="16:9", fps=30, music={"path": "/music/t.mp3", **BY},
           scenes=[{"id": "a", "type": "title", "title": "Hi", "duration_s": 2}])
    h = S.persist(s)
    mp4 = work / "out" / "delivery.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    (mp4.with_suffix(".receipt.json")).write_text(json.dumps({"quality": "delivery", "mix": {"voice": False}}))
    assert R.credits_finding(s)["code"] == "credits_missing"
    A.write_credits(s)
    assert R.credits_finding(s) is None
    assert R.credits_finding(mk(music={"path": "/music/t.mp3", "license": "CC0 1.0"})) is None  # nothing required
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R, "_probe", lambda v: {"width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0})
        mp.setattr(R, "_probe_audio", lambda v: None)
        mp.setattr(R, "_var", lambda v, t: 10.0)
        v = R.verify(str(mp4), h)
    assert "credits_missing" not in [f["code"] for f in v["findings"]] and v["music_license"] == "CC BY 4.0"


def test_verify_reads_the_credit_next_to_the_video(work):
    """A later render unlinks /work/CREDITS.txt: the copy written with the video must still verify."""
    s = mk(aspect="16:9", fps=30, music={"path": "/music/t.mp3", **BY})
    mp4 = work / "out" / "abc123" / "delivery.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    A.write_credits(s, mp4.parent)
    (work / "CREDITS.txt").unlink()
    assert R.credits_finding(s, mp4) is None
    assert R.credits_finding(s)["code"] == "credits_missing"  # the shared file alone is gone
