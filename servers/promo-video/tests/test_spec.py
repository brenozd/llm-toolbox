import shutil
import subprocess

import pytest

from promo_video_mcp import config, safety, scan, spec as S


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def codes(s):
    return {f["code"] for f in S.lint(s)}


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


def test_container_path_in_on_screen_text_is_a_warning():
    s = S.normalize({"scenes": [{"id": "a", "type": "bullets", "heading": "Run it",
                                 "items": ["/work/leak.c is the demo", "mint_loader ./leak"]}]})
    got = [f for f in S.lint(s) if f["code"] == "container_path"]
    assert [(f["scene"], f["severity"]) for f in got] == [("a", "warn")]
    assert "/work/leak.c" in got[0]["message"]
    s["scenes"][0]["items"] = ["mint_loader ./leak"]  # a repo-relative path is what we want
    assert "container_path" not in codes(s)
