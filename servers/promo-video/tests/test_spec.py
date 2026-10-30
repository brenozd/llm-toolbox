import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from promo_video_mcp import config, safety, scan, spec as S


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def codes(s):
    return {f["code"] for f in S.lint(s)} - {"no_direction"}  # every spec without a direction warns; not what this test is about


def test_ok():
    assert codes(mk()) == set()


def test_uncited_stat_blocked_and_cited_ok():
    s = mk(scenes=[{"id": "a", "type": "title", "title": "100% faster"}])
    assert "uncited_stat" in codes(s)
    s["scenes"][0]["evidence"] = "README.md:3"
    assert "uncited_stat" not in codes(s)


def test_bad_inputs():
    s = mk(scenes=[{"id": "a", "type": "nope"}, {"id": "a", "type": "title", "title": "x", "duration_s": 99}])
    assert {"bad_type", "bad_id", "duration"} <= codes(s)


def test_timeline_total_and_hash_stable():
    s = mk(scenes=[{"id": "a", "type": "title", "title": "a", "duration_s": 3}, {"id": "b", "type": "title", "title": "b", "duration_s": 3}])
    tl = S.timeline(s)
    assert tl["frames"] == 6 * 30 - tl["trans"]
    assert S.spec_hash(s) == S.spec_hash(S.normalize(s))


def fake_audio(monkeypatch, **durs):
    """A narration manifest without a TTS engine: timeline() only reads the measured durations."""
    man = {"scenes": {k: {"duration_s": v} for k, v in durs.items()}}
    monkeypatch.setattr(S, "audio_manifest", lambda spec: man)


def test_the_last_scene_pays_no_transition(monkeypatch):
    """A scene pays for the transition it is overlapped *by*, and nothing follows the closing scene: paying
    there bought a silent tail instead of picture (mint ended on 1.082 s of silence)."""
    fake_audio(monkeypatch, a=4.0, b=6.0)
    s = S.normalize({"fps": 30, "transition_s": 0.5, "scenes": [
        {"id": "a", "type": "title", "title": "a", "duration_s": 1},
        {"id": "b", "type": "title", "title": "b", "duration_s": 1}]})
    tl = S.timeline(s)
    assert tl["trans"] == 15
    assert tl["scenes"][0]["dur"] == round((4.0 + S.AUDIO_TAIL + 0.5) * 30)  # b overlaps it: it pays
    assert tl["scenes"][1]["dur"] == round((6.0 + S.AUDIO_TAIL) * 30)  # nothing follows: the tail only
    assert tl["frames"] == tl["scenes"][0]["dur"] + tl["scenes"][1]["dur"] - 15


def test_the_mint_tail_loses_the_transition(monkeypatch):
    """verify.json of the mint delivery: 892 frames (29.733 s) with 1.082 s of silence after the last cue,
    because the closing scene was stretched to narration + AUDIO_TAIL + transition. The same speech now
    ends at 877 frames (29.233 s), so the tail drops by exactly the 0.5 s transition (1.082 -> 0.582)."""
    narr = 892 / 30 - S.AUDIO_TAIL - 0.5  # the duration the old formula had been stretched to
    assert round((narr + S.AUDIO_TAIL + 0.5) * 30) == 892  # reproduces the reported delivery
    fake_audio(monkeypatch, solo=narr)
    s = S.normalize({"fps": 30, "scenes": [{"id": "solo", "type": "title", "title": "x", "duration_s": 2}]})
    tl = S.timeline(s)
    assert tl["frames"] == 892 - tl["trans"] == 877
    assert tl["frames"] / tl["fps"] == pytest.approx(29.233, abs=1e-3)
    assert pytest.approx(1.082 - tl["trans"] / tl["fps"], abs=1e-3) == 0.582


def test_a_last_scene_keeps_its_own_duration_when_it_is_longer(monkeypatch):
    """Dropping the overlap must not shrink a scene that holds longer than its line."""
    fake_audio(monkeypatch, a=1.0, hold=2.0)
    s = S.normalize({"scenes": [{"id": "a", "type": "title", "title": "a", "duration_s": 1},
                                 {"id": "hold", "type": "title", "title": "b", "duration_s": 6}]})
    assert S.timeline(s)["scenes"][1]["dur"] == 6 * 30


def test_music_dir_is_the_mount_point_and_can_be_moved():
    """MUSIC_DIR is where the host mounts the music cache (plugin.json: /music); PROMO_MUSIC_DIR points
    the same cache somewhere else instead of hardcoding the default."""
    def music_dir(value: str | None = None) -> str:
        env = {k: v for k, v in os.environ.items() if k != "PROMO_MUSIC_DIR"}
        if value is not None:
            env["PROMO_MUSIC_DIR"] = value
        r = subprocess.run([sys.executable, "-c", "from promo_video_mcp import config; print(config.MUSIC_DIR)"],
                           capture_output=True, text=True, env=env, check=True,
                           cwd=str(Path(S.__file__).resolve().parent.parent))
        return r.stdout.strip()

    assert music_dir() == "/music"
    assert music_dir("/mnt/music") == "/mnt/music"


def test_safe_path_blocks_secrets_and_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO", tmp_path)
    (tmp_path / ".env").write_text("K=1")
    with pytest.raises(PermissionError):
        safety.safe_path(tmp_path / ".env")
    with pytest.raises(PermissionError):
        safety.safe_path("/etc/passwd")


def test_say_missing_ignores_prose_but_flags_identifiers():
    """Bullets are prose: 'the', 'and', 'repo' must not be flagged as unpronounceable identifiers."""
    prose = S.normalize({"lang": "en", "scenes": [{"id": "a", "type": "bullets", "heading": "The repo and the build",
                                                   "items": ["the repo and the build, and the tests"],
                                                   "narration": "The repo and the build are here.", "duration_s": 5}]})
    assert "say_missing" not in codes(prose)
    pt = S.normalize({"lang": "pt-BR", "scenes": [{"id": "a", "type": "title", "title": "O repositório",
                                                   "narration": "O repositório e o build estão aqui.", "duration_s": 5}]})
    assert "say_missing" not in codes(pt)
    ident = S.normalize({"lang": "en", "scenes": [{"id": "b", "type": "code", "code": "LD_PRELOAD=1 ./app", "source": "a:1",
                                                   "narration": "Run LD_PRELOAD, then snake_case, camelCase and --flag",
                                                   "duration_s": 6}]})
    msgs = " ".join(f["message"] for f in S.lint(ident) if f["code"] == "say_missing")
    for tok in ("LD_PRELOAD", "snake_case", "camelCase", "--flag"):
        assert tok in msgs, tok


def test_lint_rejects_a_focus_outside_the_capture_and_a_bad_zoom():
    def mkimg(**kw):
        return S.normalize({"scenes": [{"id": "a", "type": "image", "image": __file__, **kw}]})

    assert "bad_focus" in codes(mkimg(focus={"x": 0.8, "y": 0.1, "w": 0.5, "h": 0.2}))  # runs past the right edge
    assert "bad_focus" in codes(mkimg(focus={"x": -0.1, "y": 0.1, "w": 0.2, "h": 0.2}))  # off the left edge
    assert "bad_focus" in codes(mkimg(focus=[0, 0, 1, 1]))
    assert "bad_focus" in codes(mkimg(focus={"x": 0.1, "y": 0.1, "w": 0, "h": 0.2}))  # nothing to zoom on
    assert "bad_zoom" in codes(mkimg(zoom=0.5))
    assert "bad_zoom" in codes(mkimg(zoom="2"))
    assert not {"bad_focus", "bad_zoom"} & codes(mkimg(focus={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.4}, zoom=2.5))


def test_scan_cli_and_env_names_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO", tmp_path)
    (tmp_path / "README.md").write_text("# demo\n\nA tool.\n\n```sh\n$ demo run\ndemo --help\ndemo x\n```\n")
    (tmp_path / ".env").write_text("SECRET=zzz")
    (tmp_path / ".env.example").write_text("API_KEY=\n")
    r = scan.scan_repo()
    assert r["kind_guess"] == "cli" and r["readme"]["commands"][0]["evidence"] == "README.md:6"
    assert r["env_var_names"] == ["API_KEY"] and ".env" in r["forbidden_skipped"]
    assert "zzz" not in str(r)


def _video(tmp_path, name, vf=None, inputs=("color=c=black:s=320x180:r=15:d=1",)):
    out = tmp_path / name
    argv = ["ffmpeg", "-y", "-loglevel", "error"]
    for i in inputs:
        argv += ["-f", "lavfi", "-i", i]
    if len(inputs) > 1:
        argv += ["-filter_complex", f"[0:v][1:v]concat=n={len(inputs)}:v=1"]
    elif vf:
        argv += ["-vf", vf]
    subprocess.run([*argv, "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                 reason="ffmpeg is needed to read a test capture")


@needs_ffmpeg
def test_sparse_capture_flags_a_take_that_only_shows_the_prompt(tmp_path):
    """A prompt on a black screen is a few pixels: raw variance hid it, a non-background ratio does not."""
    screen = "color=c=black:s=1444x596:r=15:d=1"  # the size an 80x16 session is grabbed at
    prompt = _video(tmp_path, "prompt.mp4", "drawbox=x=2:y=2:w=13:h=19:color=white:t=fill", (screen,))
    real = _video(tmp_path, "real.mp4", "drawbox=x=2:y=2:w=13:h=19:color=white:t=fill,"
                                        "drawbox=x=20:y=2:w=560:h=19:color=gray:t=fill,"
                                        "drawbox=x=2:y=28:w=700:h=19:color=gray:t=fill", (screen,))
    s = S.normalize({"scenes": [{"id": "a", "type": "terminal", "video": str(prompt)},
                                {"id": "b", "type": "terminal", "video": str(real)}]})
    assert [f["scene"] for f in S.lint(s) if f["code"] == "sparse_capture"] == ["a"]


@needs_ffmpeg
def test_sparse_capture_samples_the_middle_of_a_recording(tmp_path):
    # frame 0 of a recording is the blank pre-roll; the take itself is what happened after it
    mid = _video(tmp_path, "mid.mp4", inputs=("color=c=black:s=320x180:r=15:d=1", "testsrc=s=320x180:r=15:d=1"))
    s = S.normalize({"scenes": [{"id": "a", "type": "terminal", "video": str(mid)}]})
    assert not [f for f in S.lint(s) if f["code"] == "sparse_capture"]


def test_a_missing_asset_is_a_lint_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO", tmp_path)
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "ok.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    s = S.normalize({"scenes": [{"id": "a", "type": "image", "image": str(tmp_path / "nope.png")},
                                {"id": "b", "type": "image", "image": "shots/ok.png"}]})
    assert [(f["scene"], f["severity"]) for f in S.lint(s) if f["code"] == "missing_file"] == [("a", "error")]


def test_exec_gate(monkeypatch):
    from promo_video_mcp import capture
    monkeypatch.setattr(config, "ALLOW_EXEC", False)
    with pytest.raises(PermissionError):
        capture.capture_terminal("echo hi")


def test_phonetic_say_form_must_not_reach_the_narration():
    """The SRT is cut from scene.narration: a spoken form written there would end up in the captions."""
    s = S.normalize({"lang": "en", "say": {"LD_PRELOAD": "el di preload"},
                     "scenes": [{"id": "a", "type": "title", "title": "LD_PRELOAD",
                                 "narration": "Preload with el di preload and it works.", "duration_s": 6}]})
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "phonetic_in_narration"] == [
        ("phonetic_in_narration", "error")]
    s["scenes"][0]["narration"] = "Preload with LD_PRELOAD and it works."  # the written form is fine
    assert "phonetic_in_narration" not in codes(s)
    s["say"] = {"LD_PRELOAD": 3}  # a non-string value must not crash the lint
    assert "phonetic_in_narration" not in codes(s)


def test_a_spoken_form_only_matches_whole_words():
    """The match used to be a substring: say={'x': 'ex'} fired on the 'ex' inside 'next'."""
    s = S.normalize({"lang": "en", "say": {"x": "ex"},
                     "scenes": [{"id": "a", "type": "title", "title": "x",
                                 "narration": "Do the next step.", "duration_s": 4}]})
    assert "phonetic_in_narration" not in codes(s)
    s = S.normalize({"lang": "en", "say": {"x": "ex"},
                     "scenes": [{"id": "a", "type": "title", "title": "x",
                                 "narration": "Run ex and it works.", "duration_s": 4}]})
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "phonetic_in_narration"] == [
        ("phonetic_in_narration", "error")]


def test_container_path_in_on_screen_text_is_a_warning():
    s = S.normalize({"scenes": [{"id": "a", "type": "bullets", "heading": "Run it",
                                 "items": ["/work/leak.c is the demo", "mint_loader ./leak"]}]})
    got = [f for f in S.lint(s) if f["code"] == "container_path"]
    assert [(f["scene"], f["severity"]) for f in got] == [("a", "warn")]
    assert "/work/leak.c" in got[0]["message"]
    s["scenes"][0]["items"] = ["mint_loader ./leak"]  # a repo-relative path is what we want
    assert "container_path" not in codes(s)


def test_container_path_in_the_narration_is_a_warning_too():
    s = S.normalize({"lang": "en", "scenes": [{"id": "a", "type": "title", "title": "Copy it",
                                                  "narration": "First, copy it from /work/repo and run it.",
                                                  "duration_s": 5}]})
    got = [f for f in S.lint(s) if f["code"] == "container_path"]
    assert [(f["scene"], f["severity"]) for f in got] == [("a", "warn")]
    assert "narration" in got[0]["message"]
    s["scenes"][0]["narration"] = "First, copy it from the repo and run it."
    assert "container_path" not in codes(s)


# --- the director's brief (spec.direction) -------------------------------------------------------

def test_direction_palette_reaches_the_theme_and_an_explicit_theme_wins():
    d = {"direction": {"palette": {"bg": "#101820", "fg": "#eef2f6", "accent": "#ffb000"}}}
    s = mk(**d)
    assert (s["theme"]["bg"], s["theme"]["accent"]) == ("#101820", "#ffb000")
    assert s["theme"]["muted"] == S.THEME["muted"]  # the palette only says what it means to say
    s = mk(theme={"accent": "#123456"}, **d)  # a manual override still beats the director
    assert (s["theme"]["accent"], s["theme"]["bg"]) == ("#123456", "#101820")


def test_motion_defaults_to_subtle_so_text_stops_growing():
    assert mk()["motion"] == "subtle"
    assert mk(direction={"motion": "still"})["motion"] == "still"
    assert mk(motion="lively", direction={"motion": "still"})["motion"] == "lively"  # explicit spec wins
    assert "bad_direction" in codes(mk(motion="bouncy"))


def test_bad_direction_values_are_errors():
    for bad in ({"purpose": "tiktok"}, {"audio": "loud"}, {"palette": {"bg": "0f1115"}},
                {"palette": "#fff"}, {"scenes": {"a": {"role": "hero"}}}, {"scenes": {"a": {"align": "edge"}}},
                {"scenes": {"a": "hook"}}, {"pacing": {"max_words_card": 0}}, {"pacing": 6},
                {"research": "https://example.com"}, {"must_avoid": "thanks"}):
        assert "bad_direction" in codes(mk(direction=bad)), bad
    assert "bad_direction" in codes(mk(direction="subtle"))  # not an object at all


def test_no_direction_only_warns_and_keeps_todays_findings():
    s = mk(scenes=[{"id": "a", "type": "title", "title": "100% faster"}])
    assert {(f["code"], f["severity"]) for f in S.lint(s)} == {("no_direction", "warn"), ("uncited_stat", "error")}


def test_a_plan_that_lags_the_timeline_only_warns():
    """4b cuts and reframe() clones change the scenes: a stale plan must never block the render."""
    s = mk(direction={"scenes": {"a": {"role": "hook"}, "cut": {"role": "cta"}}})
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "scene_unused"] == [("scene_unused", "warn")]
    assert not [f for f in S.lint(s) if f["severity"] == "error"]
    s = mk(direction={"scenes": {"b": {"role": "value"}}})
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "no_role"] == [("no_role", "warn")]


def test_align_comes_from_the_plan_then_from_the_type():
    s = mk(scenes=[{"id": "a", "type": "title", "title": "Hi"}, {"id": "b", "type": "bullets", "heading": "H",
                                                                   "items": ["x"]}],
           direction={"scenes": {"a": {"align": "left"}}})
    assert [sc["align"] for sc in s["scenes"]] == ["left", "left"]
    assert mk(scenes=[{"id": "a", "type": "title", "title": "Hi"}])["scenes"][0]["align"] == "center"


def test_palette_contrast_blocks_our_palette_but_only_warns_on_the_users():
    dark = {"bg": "#111111", "fg": "#1c1c1c"}  # 1.1:1: nobody reads that
    assert "palette_contrast" in codes(mk(direction={"palette": dark}))
    user = {"palette": dark, "palette_source": "user"}
    assert [(f["code"], f["severity"]) for f in S.lint(mk(direction=user)) if f["code"] == "palette_contrast"] == [
        ("palette_contrast", "warn")]


def test_a_booth_loop_needs_seven_to_one():
    ok = {"bg": "#0f1115", "fg": "#8b93a1"}  # 6.1:1: passes AA, not the hall
    assert "palette_contrast" in codes(mk(direction={"purpose": "booth-loop", "palette": ok}))
    assert "palette_contrast" not in codes(mk(direction={"purpose": "feature-demo", "palette": ok}))


def test_narration_must_match_the_plan():
    plan = {"scenes": {"a": {"role": "value", "narration": False}}}
    s = mk(lang="en", direction=plan, scenes=[{"id": "a", "type": "title", "title": "Hi",
                                               "narration": "spoken anyway", "duration_s": 4}])
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "narration_off_plan"] == [
        ("narration_off_plan", "error")]
    s = mk(direction={"scenes": {"a": {"role": "value", "narration": True}}})
    assert [(f["code"], f["severity"]) for f in S.lint(s) if f["code"] == "narration_off_plan"] == [
        ("narration_off_plan", "warn")]


def test_wordy_cap_and_must_avoid_come_from_the_plan():
    line = "one two three four five six seven"  # 7 words: fine at the default 18, too long at 6
    s = mk(direction={"pacing": {"max_words_card": 6}, "must_avoid": ["thanks for watching"]},
           scenes=[{"id": "a", "type": "title", "title": line}])
    assert "wordy" in codes(s)
    s = mk(direction={"pacing": {"max_words_card": 8}}, scenes=[{"id": "a", "type": "title", "title": line}])
    assert "wordy" not in codes(s)
    s = mk(direction={"must_avoid": ["Thanks for watching"]},
           scenes=[{"id": "a", "type": "title", "title": "thanks for watching, see you"}])
    assert [(f["code"], f["severity"], f["scene"]) for f in S.lint(s) if f["code"] == "must_avoid"] == [
        ("must_avoid", "warn", "a")]


def test_spec_hash_follows_the_palette_and_the_motion():
    still, lively = mk(direction={"motion": "still"}), mk(direction={"motion": "lively"})
    pal = mk(direction={"palette": {"bg": "#202020", "fg": "#ffffff"}})
    assert len({S.spec_hash(still), S.spec_hash(lively), S.spec_hash(pal)}) == 3


def test_an_empty_direction_is_no_direction():
    assert [(f["code"], f["severity"]) for f in S.lint(mk(direction={}))] == [("no_direction", "warn")]


def test_a_theme_colour_the_render_cannot_parse_is_an_error():
    assert "bad_theme" in codes(mk(theme={"bg": "#fff"}))  # build_html derives panel/line from these hexes
    assert "bad_theme" in codes(mk(theme={"fg": "white"}))
    assert "bad_theme" not in codes(mk(theme={"bg": "#ffffff"}))


def test_a_low_contrast_theme_is_measured_even_without_a_direction():
    dark = {"bg": "#111111", "fg": "#1c1c1c"}  # 1.1:1
    got = [(f["code"], f["severity"]) for f in S.lint(mk(theme=dark)) if f["code"] == "palette_contrast"]
    assert got == [("palette_contrast", "warn")]  # no brief: an older spec still renders, but it is said


def test_a_theme_that_is_not_an_object_is_a_finding_not_a_traceback():
    """`theme: "white"` used to raise TypeError inside normalize, so validate_spec returned a traceback."""
    for bad in ("white", ["#ffffff"], 3):
        assert codes(mk(theme=bad)) == {"bad_theme"}, bad
    assert codes(mk(theme="white", direction={"purpose": "feature-demo"})) == {"bad_theme"}


def test_evidence_must_be_file_line_and_the_file_must_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO", tmp_path)
    (tmp_path / "README.md").write_text("# demo\n")

    def ev(v):
        sc = [{"id": "a", "type": "title", "title": "3x faster", "evidence": v}]
        return [(f["code"], f["severity"]) for f in S.lint(mk(scenes=sc)) if f["code"] in ("bad_evidence", "uncited_stat")]

    assert ev("README.md:3") == []  # file:line is the shape the audit reads
    assert ev("README.md:3-9") == []
    assert ev("total nonsense") == [("bad_evidence", "error")]  # junk evidence used to silence uncited_stat
    assert ev("README.md") == [("bad_evidence", "error")]  # no line: nothing to check
    assert ev("nope.c:9") == [("bad_evidence", "error")]  # the file proving the claim is not there
    assert ev(None) == [("uncited_stat", "error")]


def test_tone_and_palette_source_are_type_checked():
    assert "bad_direction" in codes(mk(direction={"tone": {"a": 1}}))
    assert "bad_direction" in codes(mk(direction={"palette_source": 1}))
    assert "bad_direction" not in codes(mk(direction={"tone": "calm technical", "palette_source": "derived"}))
