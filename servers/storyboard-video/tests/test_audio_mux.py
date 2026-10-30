import json
import shutil
import wave

import pytest

from storyboard_video_mcp import config, render as R, spec as S


def mk_scene(sid, **kw):
    return {"id": sid, "type": "title", "title": sid, "duration_s": 3, **kw}


def fake_manifest(spec, tmp, durations):
    """Write the manifest narrate() would have written: same shapes, real WAVs of the given length."""
    h = S.spec_hash(spec)
    d = tmp / "audio" / h
    d.mkdir(parents=True)
    scenes = {}
    for sc in spec["scenes"]:
        dur = durations.get(sc["id"])
        if not dur:
            continue
        p = d / f"{sc['id']}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x10\x27" * int(24000 * dur))
        scenes[sc["id"]] = {"key": sc["id"], "path": str(p), "duration_s": dur, "text": sc["narration"]}
    (d / "manifest.json").write_text(json.dumps({"spec_hash": h, "scenes": scenes}))
    return scenes


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def test_srt_uses_narration_and_the_measured_duration(work):
    s = S.normalize({"lang": "pt-BR", "scenes": [
        mk_scene("a", narration="Um dois três.", duration_s=5),
        mk_scene("b", caption="Legenda muda", duration_s=3)]})
    fake_manifest(s, work, {"a": 1.0})
    tl = S.timeline(s)
    assert tl["scenes"][0]["dur"] == 150  # 5 s: the scene is already longer than 1 s of speech
    cues = R.srt(s)
    assert "Um dois três." in cues and "Legenda muda" in cues
    # the spoken cue lasts the audio, not the (longer) scene; the silent one keeps the whole scene
    assert "00:00:00,000 --> 00:00:01,000" in cues
    start = tl["scenes"][1]["start"] / tl["fps"]
    assert f"{R._fmt(start)} --> {R._fmt(start + 3)}" in cues


def test_narration_track_places_each_scene_at_its_offset(work):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    s = S.normalize({"fps": 10, "transition_s": 0, "lang": "pt-BR", "scenes": [
        mk_scene("a", narration="aaa", duration_s=2), mk_scene("b", narration="bbb", duration_s=2)]})
    fake_manifest(s, work, {"a": 0.5, "b": 0.5})
    track = R.narration_track(s)
    assert track and track.is_file()
    total = S.timeline(s)["frames"] / S.timeline(s)["fps"]
    with wave.open(str(track), "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - total) < 0.05  # padded to the picture length
        frames = w.readframes(w.getnframes())
    assert frames[:1000] != b"\x00" * 1000  # speech starts at t=0
    # scene b starts at 2 s: between the end of a (0.5 s) and 2 s the track is silent (dither aside)
    def peak(t0, t1):
        seg = frames[int(t0 * 48000) * 2:int(t1 * 48000) * 2]
        return max(abs(int.from_bytes(seg[i:i + 2], "little", signed=True)) for i in range(0, len(seg), 2))
    assert peak(0.8, 1.6) == 0  # silence between the two lines
    assert peak(2.05, 2.4) > 1000  # scene b's line starts with its scene


def test_every_narrated_line_starts_with_its_scene(work):
    """Scenes overlap by the transition, so a scene sized audio+tail used to start the next line late and
    the drift grew per scene; the line must land on its scene and never be pushed by the previous one."""
    ids = [f"s{i}" for i in range(6)]
    s = S.normalize({"fps": 30, "lang": "pt-BR",
                     "scenes": [mk_scene(i, narration=f"Linha {i} dita devagar.", duration_s=3) for i in ids]})
    fake_manifest(s, work, {i: 3.135 for i in ids})
    tl = S.timeline(s)
    cues = R.narration_cues(s)
    for c, t in zip(cues, tl["scenes"]):
        assert c["start_s"] == pytest.approx(t["start"] / tl["fps"], abs=1e-9)  # no accumulated push
        assert c["start_s"] + c["dur_s"] <= (t["start"] + t["dur"]) / tl["fps"]  # inside its own scene
    assert cues[-1]["start_s"] + cues[-1]["dur_s"] <= tl["frames"] / tl["fps"]  # nothing clipped


def test_srt_cues_never_overlap(work):
    s = S.normalize({"fps": 30, "scenes": [
        mk_scene("a", narration="Fala curta.", duration_s=2), mk_scene("b", caption="Legenda muda", duration_s=3),
        mk_scene("c", narration="Outra fala.", duration_s=2)]})
    fake_manifest(s, work, {"a": 1.0, "c": 1.0})
    cues = R.narration_cues(s)
    for c, nxt in zip(cues, cues[1:]):
        assert c["start_s"] + c["dur_s"] <= nxt["start_s"] + 1e-9


def test_narrated_follows_the_spec_not_only_the_manifest(work):
    s = S.normalize({"scenes": [mk_scene("a", narration="Tem fala.", duration_s=3)]})
    assert R.narrated(s)  # narration in the spec, narrate never run: still a promised voice-over
    assert R.audio_findings(5.0, R.narrated(s), None)[0]["code"] == "no_audio"
    fake_manifest(s, work, {"a": 1.0})
    assert R.narrated(s)
    assert R.narrated(S.normalize({"scenes": [mk_scene("a", duration_s=3)]})) is False


def test_verify_reports_narration_from_the_spec(work, monkeypatch):
    """verify must wire the *spec's* promise into the audio check (a silent render of a narrated spec
    is an error), not just read the manifest."""
    s = S.normalize({"aspect": "16:9", "fps": 30, "scenes": [mk_scene("a", narration="Fala.", duration_s=2)]})
    h = S.persist(s)
    mp4 = work / "out" / "draft.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    monkeypatch.setattr(R, "_probe", lambda v: {"width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0})
    monkeypatch.setattr(R, "_probe_audio", lambda v: None)
    monkeypatch.setattr(R, "_var", lambda v, t: 10.0)
    v = R.verify(str(mp4), h)
    assert v["narrated"] is True and v["audio"] is None
    assert [f["code"] for f in v["findings"]] == ["no_audio"]
    silent = S.persist(S.normalize({"aspect": "16:9", "fps": 30, "scenes": [mk_scene("b", duration_s=2)]}))
    v = R.verify(str(mp4), silent)
    assert v["status"] == "ok" and v["narrated"] is False and v["findings"] == []


def test_audio_findings_require_audio_and_matching_duration():
    assert R.audio_findings(5.0, True, None)[0]["code"] == "no_audio"
    assert R.audio_findings(5.0, False, None) == []
    assert R.audio_findings(5.0, True, {"duration_s": 5.05}) == []
    assert R.audio_findings(5.0, True, {"duration_s": 4.5})[0]["code"] == "audio_duration"
    assert R.audio_findings(5.0, False, {"duration_s": 5.0})[0]["severity"] == "warn"


def test_a_music_bed_alone_is_not_a_voice_over():
    """Any audio stream used to satisfy verify: a spec that promises narration must carry the voice, so a
    bed-only mix of a never-narrated spec is an error, not a quiet ok."""
    au = {"duration_s": 5.0}
    assert R.audio_findings(5.0, True, au) == []  # no receipt (an older render): unchanged
    assert R.audio_findings(5.0, True, au, True) == []
    assert R.audio_findings(5.0, True, au, False)[0]["code"] == "no_voice"
    # no narration promised and the receipt names the bed that was mixed in: the audio is expected
    assert R.audio_findings(5.0, False, au, False, "/music/track.mp3") == []
    # ...a stream the receipt cannot explain (an old receipt, or none) is still worth a warning
    assert R.audio_findings(5.0, False, au, False)[0]["code"] == "unexpected_audio"
    assert R.audio_findings(5.0, False, au)[0]["code"] == "unexpected_audio"


def test_verify_reads_the_voice_out_of_the_render_receipt(work, monkeypatch):
    s = S.normalize({"aspect": "16:9", "fps": 30, "scenes": [mk_scene("a", narration="Fala.", duration_s=2)]})
    h = S.persist(s)
    mp4 = work / "out" / "delivery.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    monkeypatch.setattr(R, "_probe", lambda v: {"width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0})
    monkeypatch.setattr(R, "_probe_audio", lambda v: {"codec": "aac", "channels": 2, "sample_rate": 48000,
                                                      "duration_s": 2.0})
    monkeypatch.setattr(R, "_var", lambda v, t: 10.0)
    monkeypatch.setattr(R.A, "check", lambda *a, **k: {"loudness": {"integrated_lufs": -16.1, "lra_lu": 2.0,
                                                                   "true_peak_db": -2.0},
                                                      "silences": [], "findings": []})
    recp = work / "out" / "delivery.receipt.json"
    recp.write_text(json.dumps({"quality": "delivery", "mix": {"voice": False}}))
    v = R.verify(str(mp4), h)
    assert v["status"] == "error" and [f["code"] for f in v["findings"]] == ["no_voice"]
    recp.write_text(json.dumps({"quality": "delivery", "mix": {"voice": True}}))
    v = R.verify(str(mp4), h)
    assert v["status"] == "ok" and v["findings"] == [] and v["loudness"]["integrated_lufs"] == -16.1


def test_verify_does_not_warn_about_the_bed_it_mixed(work, monkeypatch):
    """A silent spec rendered with a music bed has an audio stream on purpose: the receipt's mix.music
    explains it. Without that track the same stream is still a warning."""
    s = S.normalize({"aspect": "16:9", "fps": 30, "scenes": [mk_scene("a", duration_s=2)]})
    h = S.persist(s)
    mp4 = work / "out" / "delivery.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    monkeypatch.setattr(R, "_probe", lambda v: {"width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0})
    monkeypatch.setattr(R, "_probe_audio", lambda v: {"codec": "aac", "channels": 2, "sample_rate": 48000,
                                                      "duration_s": 2.0})
    monkeypatch.setattr(R, "_var", lambda v, t: 10.0)
    monkeypatch.setattr(R.A, "check", lambda *a, **k: {"loudness": {"integrated_lufs": -16.1, "lra_lu": 2.0,
                                                                   "true_peak_db": -2.0},
                                                      "silences": [], "findings": []})
    recp = work / "out" / "delivery.receipt.json"
    recp.write_text(json.dumps({"quality": "delivery", "mix": {"voice": False, "music": "/music/x.mp3"}}))
    v = R.verify(str(mp4), h)
    assert v["status"] == "ok" and [f["code"] for f in v["findings"]] == []
    recp.write_text(json.dumps({"quality": "delivery", "mix": {"voice": False}}))
    v = R.verify(str(mp4), h)
    assert [f["code"] for f in v["findings"]] == ["unexpected_audio"]


def test_verify_looks_around_a_dark_checkpoint(work, monkeypatch):
    """A scene's entrance frame and a crossfade tail are legitimately black, so one sampled frame used to
    report blank_frame for a video with plenty of picture. A +-0.25 s window (max variance) fixes it, and
    an all-black video still fails -- the window must not become a lower bar."""
    s = S.normalize({"aspect": "16:9", "fps": 30, "scenes": [mk_scene("a", duration_s=2)]})
    h = S.persist(s)
    mp4 = work / "out" / "delivery.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    monkeypatch.setattr(R, "_probe", lambda v: {"width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0})
    monkeypatch.setattr(R, "_probe_audio", lambda v: None)
    # the 50% checkpoint (1.0 s of 2 s) is exactly the next scene's entrance: black at that instant only
    monkeypatch.setattr(R, "_var", lambda v, t: 0.1 if abs(t - 1.0) < 1e-6 else 4.0)
    v = R.verify(str(mp4), h)
    assert v["status"] == "ok" and v["findings"] == []
    monkeypatch.setattr(R, "_var", lambda v, t: 0.1)  # a video with no picture anywhere still fails
    v = R.verify(str(mp4), h)
    assert [f["code"] for f in v["findings"]] == ["blank_frame"] * 3
