import hashlib
import json
import shutil
import subprocess

import pytest

from storyboard_video_mcp import audio as A, config, sfx, spec as S

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_synth_is_reproducible_and_kind_checked(work):
    a = sfx.synth("whoosh")
    h = _sha(a)
    a.unlink()
    assert _sha(sfx.synth("whoosh")) == h  # same recipe, same bytes
    with pytest.raises(ValueError):
        sfx.synth("laser")


def test_track_places_events_and_audio_sfx_false_disables(work):
    spec = {"fps": 30, "scenes": [{"id": "a", "sfx": [{"at": 0.5, "kind": "tick"}]},
                                  {"id": "b", "sfx": [{"at": 0, "kind": "hit", "gain_db": -10}, {"at": "x", "kind": "pop"}]}]}
    tl = {"fps": 30, "frames": 180, "scenes": [{"start": 0, "dur": 90}, {"start": 90, "dur": 90}]}
    assert [(t, f.name) for t, f, _ in sfx.events(spec, tl)] == [(0.5, "tick-v2.wav"), (3.0, "hit-v2.wav")]
    out = sfx.track(spec, tl, work / "o" / "sfx.wav")
    assert out.stat().st_size > 48000 * 2 * 5  # padded to the whole video
    assert sfx.track({**spec, "audio": {"sfx": False}}, tl, work / "n.wav") is None


def test_lint_sfx():
    base = {"lang": "en", "scenes": [{"id": "a", "type": "title", "heading": "x", "duration_s": 2}]}
    def codes(ev):
        sp = S.normalize({**base, "scenes": [{**base["scenes"][0], "sfx": ev}]})
        return {f["code"] for f in S.lint(sp)}
    assert "bad_sfx" in codes([{"kind": "laser", "at": 1}]) and "bad_sfx" in codes("tick")
    assert "sfx_density" in codes([{"kind": "tick", "at": 0}, {"kind": "tick", "at": 1}])
    assert not codes([{"kind": "tick", "at": 0.2}]) & {"bad_sfx", "sfx_density"}


def test_sfx_stays_out_of_the_duck_and_is_mixed_after_it(work):
    g = A.mix_graph(10, True, True, -18, 12, 0, sfx=True)
    assert g.index("sidechaincompress") < g.index("[2:a]") and "[pre][fx]amix" in g
    assert A.mix_graph(10, True, True, -18, 12, 0) .endswith("[out]")  # without sfx: unchanged


def _tone(path, seconds, freq, gain):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-af", f"volume={gain}", str(path)], check=True)
    return path


def test_mix_with_sfx_has_the_picture_length_and_duck_margin_is_measured(work):
    bed = _tone(work / "bed.wav", 8, 220, "-6dB")
    voice = _tone(work / "voice.wav", 4, 440, "-12dB")
    s = S.normalize({"fps": 10, "lang": "en", "music": {"path": str(bed), "license": "CC0 1.0", "volume_db": -6, "duck": 12},
                     "scenes": [{"id": "a", "type": "title", "title": "a", "duration_s": 8, "narration": "Hi.",
                                 "sfx": [{"at": 5, "kind": "pop"}]}]})
    tl = S.timeline(s)
    fx = sfx.track(s, tl, work / "fx.wav")
    out = A.build(s, voice, 8.0, work / "mix.wav", fx)
    import wave
    with wave.open(str(out), "rb") as w:
        assert abs(w.getnframes() / 48000 - 8.0) < 0.1
    m = A.duck_margin_db(s, voice, 8.0)
    assert m is not None and m > 0  # the voice sits above the ducked bed
    assert A.duck_margin_db(s, None, 8.0) is None
    assert not list(work.glob("stem-*.wav"))


def test_library_effect_and_cue_bound_effect(work, monkeypatch):
    lib = work / "sfxlib"
    lib.mkdir()
    monkeypatch.setattr(config, "SFX_DIR", lib)
    clip = _tone(lib / "whoosh-1.wav", 0.5, 300, "-6dB")
    sc = {"id": "a", "type": "bullets", "items": ["x", "y"], "duration_s": 6, "narration": "Primeiro isto depois aquilo.",
          "cues": [{"on": "depois aquilo", "item": 1}],
          "sfx": [{"at": "cue:0", "path": str(clip), "license": "CC0 1.0", "title": "Whoosh", "source_url": "https://x"},
                  {"at": "cue:5", "kind": "tick"},          # no such cue
                  {"at": 1, "path": str(clip), "license": "CC BY 4.0"},  # not CC0: plays nothing
                  {"at": 1, "path": str(lib / "missing.wav"), "license": "CC0 1.0"}]}
    spec = {"fps": 30, "scenes": [sc]}
    tl = {"fps": 30, "frames": 180, "scenes": [{"start": 0, "dur": 180}]}
    ev = sfx.events(spec, tl, {"a": {0: 2.5}})
    assert [(t, f.name) for t, f, _ in ev] == [(2.5, "whoosh-1.wav")]
    assert sfx.events(spec, tl, {}) == []  # an unresolved cue plays nothing
    assert sfx.track(spec, tl, work / "o.wav", {"a": {0: 2.5}}).exists()
    codes = [f["code"] for f in S.lint(S.normalize({"lang": "pt-BR", "scenes": [sc]}))]
    assert codes.count("bad_sfx") == 1 and "sfx_license_incompatible" in codes and "sfx_path_missing" in codes
    assert sfx.credits(spec)[0].startswith("- Whoosh")
    assert "Sound effect credits" in A.credits_text(spec)
    assert A.credits_text({"scenes": [{"id": "a"}]}) is None


def _manifest(work, spec, seconds):
    """A manifest as narrate() writes it: the scene's voice runs `seconds` long, so it stretches."""
    d = work / "audio" / S.spec_hash(spec)
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"scenes": {"a": {"duration_s": seconds}}}))


def test_an_effect_past_the_scene_end_warns(work):
    """sfx.events drops an effect at/after the scene's end: the lint says so instead of leaving silence."""
    def codes(sc):
        return [f["code"] for f in S.lint(S.normalize({"lang": "en", "scenes": [sc]}))]
    base = {"id": "a", "type": "title", "title": "x", "duration_s": 2}
    assert "sfx_past_scene" in codes({**base, "sfx": [{"at": 2, "kind": "tick"}]})  # the end frame is dropped
    assert "sfx_past_scene" not in codes({**base, "sfx": [{"at": 1.9, "kind": "tick"}]})
    sp = S.normalize({"lang": "en", "scenes": [{**base, "narration": "We ship the fix.",
                                                "sfx": [{"at": 5, "kind": "tick"}]}]})
    _manifest(work, sp, 10)  # the voice stretches the scene: 5 s is inside it, whatever duration_s says
    assert "sfx_past_scene" not in [f["code"] for f in S.lint(sp)]


def test_sfx_density_counts_the_narrated_length(work):
    """Four effects over a scene the voice stretches to 10 s is not clutter; over 2 s it is."""
    sc = {"id": "a", "type": "title", "title": "x", "duration_s": 2, "narration": "We ship the fix.",
          "sfx": [{"at": 0, "kind": "tick"}, {"at": 1, "kind": "tick"},
                  {"at": 2.5, "kind": "tick"}, {"at": 4, "kind": "tick"}]}
    sp = S.normalize({"lang": "en", "scenes": [sc]})
    assert "sfx_density" in [f["code"] for f in S.lint(sp)]  # no manifest: the 2 s spec is all we know
    _manifest(work, sp, 10)
    assert "sfx_density" not in [f["code"] for f in S.lint(sp)]


def test_a_cue_with_no_match_is_reported_once(work):
    """cue_unmatched already names the cue the narration never says: the effect on it adds no finding."""
    sp = S.normalize({"lang": "en", "scenes": [{"id": "a", "type": "bullets", "heading": "H", "items": ["x"],
                                                "duration_s": 4, "narration": "We ship the fix.",
                                                "cues": [{"on": "nunca dito", "item": 0}],
                                                "sfx": [{"at": "cue:0", "kind": "tick"}]}]})
    codes = [f["code"] for f in S.lint(sp)]
    assert codes.count("cue_unmatched") == 1 and "sfx_cue_unmatched" not in codes


def test_infinite_or_huge_at_is_refused():
    sc = {"id": "a", "type": "bullets", "items": ["x"], "duration_s": 4, "narration": "oi",
          "sfx": [{"at": float("inf"), "kind": "tick"}, {"at": 1e9, "kind": "tick"}]}
    codes = [f["code"] for f in S.lint(S.normalize({"lang": "pt-BR", "scenes": [sc]}))]
    assert codes.count("bad_sfx") == 2


def test_procedural_effects_peak_near_minus_three(tmp_path, monkeypatch):
    import subprocess
    from storyboard_video_mcp import config, sfx
    monkeypatch.setattr(config, "WORK", tmp_path)
    for k in sfx.KINDS:
        o = subprocess.run(["ffmpeg", "-i", str(sfx.synth(k)), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        peak = float(next(l for l in o.splitlines() if "max_volume" in l).split(":")[1].split("dB")[0])
        assert -4.5 < peak < -2.0, (k, peak)
