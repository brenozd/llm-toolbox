"""Three audio-truth lints: an effect with no mix to play on, a pause on a scene that never speaks, and
a [beat] at the edge of a line (which tts.synthesize drops). All `warn`, all with a `fix`."""
from storyboard_video_mcp import config, spec as S

NEW_CODES = {"sfx_without_audio", "pause_ignored", "beat_at_edge"}


def mk(*scenes, **kw):
    return S.normalize({"lang": "en", "scenes": list(scenes) or [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def got(s, code):
    return [(f["code"], f["severity"], f["scene"]) for f in S.lint(s) if f["code"] == code]


def silent(sid="a", **kw):
    return {"id": sid, "type": "title", "title": f"beat {sid}", "duration_s": 3, **kw}


def voiced(sid="a", narration="We ship the fix.", **kw):
    return {"id": sid, "type": "title", "title": f"beat {sid}", "duration_s": 3, "narration": narration, **kw}


def test_sfx_without_audio_warns_when_nothing_would_play_them():
    s = mk(silent(sfx=[{"at": 0.5, "kind": "tick"}]))
    assert got(s, "sfx_without_audio") == [("sfx_without_audio", "warn", None)]


def test_sfx_without_audio_is_quiet_when_a_voice_or_a_bed_exists(tmp_path, monkeypatch):
    sfx = [{"at": 0.5, "kind": "tick"}]
    # a narrated scene: audio.build gets a voice track to mix the effects into
    assert got(mk(silent(sfx=sfx), voiced("b")), "sfx_without_audio") == []
    # audio.sfx: false turns the effects off on purpose: nothing to warn about
    assert got(mk(silent(sfx=sfx), audio={"sfx": False}), "sfx_without_audio") == []
    # a staged music bed is a stem too, even with nobody speaking
    monkeypatch.setattr(config, "WORK", tmp_path)
    (tmp_path / "bed.mp3").write_bytes(b"\0")
    bed = mk(silent(sfx=sfx), music={"path": str(tmp_path / "bed.mp3"), "license": "CC0 1.0"})
    assert got(bed, "sfx_without_audio") == []


def test_pause_ignored_warns_on_a_scene_that_never_speaks():
    assert got(mk(silent(pause_after_s=0.5)), "pause_ignored") == [("pause_ignored", "warn", "a")]
    assert got(mk(silent(audio_lead_s=0.3)), "pause_ignored") == [("pause_ignored", "warn", "a")]


def test_pause_ignored_is_quiet_with_a_line_a_zero_pause_or_a_bad_value():
    # the lint runs before narrate: no WAV yet is not a reason to warn
    assert got(mk(voiced(pause_after_s=0.5, audio_lead_s=0.3)), "pause_ignored") == []
    assert got(mk(silent(pause_after_s=0, audio_lead_s=0)), "pause_ignored") == []
    assert got(mk(silent(pause_after_s="x")), "pause_ignored") == []  # bad_pause already says it


def test_beat_at_edge_warns_when_the_marker_has_nothing_to_pause_between():
    assert got(mk(voiced(narration="[beat] We ship the fix.")), "beat_at_edge") == [("beat_at_edge", "warn", "a")]
    assert got(mk(voiced(narration="We ship the fix. [beat]")), "beat_at_edge") == [("beat_at_edge", "warn", "a")]


def test_beat_at_edge_is_quiet_between_two_ideas():
    assert got(mk(voiced(narration="We ship the fix [beat] and the leak is gone.")), "beat_at_edge") == []
    assert got(mk(voiced(narration="No marker at all.")), "beat_at_edge") == []


def test_a_legacy_spec_gains_zero_new_findings():
    """No direction, no cues, no sfx: the spec an older skill produced keeps exactly its one finding."""
    s = mk(silent("a"), {"id": "b", "type": "bullets", "heading": "What it does", "duration_s": 3,
                         "items": ["one two", "three four"]})
    assert [(f["code"], f["severity"]) for f in S.lint(s)] == [("no_direction", "warn")]
    assert not ({f["code"] for f in S.lint(s)} & NEW_CODES)


def test_a_spec_with_a_direction_and_roles_gains_none_of_them():
    """The brief and the plan change what the narrative lints judge, not these three: still nothing."""
    s = mk(voiced("a"), {"id": "b", "type": "bullets", "heading": "What it does", "duration_s": 3,
                         "items": ["one two"], "narration": "We ship the fix."},
           direction={"tone": "calm", "scenes": {"a": {"role": "hook"}, "b": {"role": "cta"}}})
    assert not ({f["code"] for f in S.lint(s)} & NEW_CODES)
