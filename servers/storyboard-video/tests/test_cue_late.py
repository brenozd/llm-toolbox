"""cue_late: a cue that reveals a bullet so late the item barely shows before the cut.

`cue_delays` (and the phrase alignment behind it) is tested in test_cues.py; the contract here is the
warn-only finding `shot_list` carries: a reveal with less than CUE_MIN_VISIBLE_S on screen is a flash,
a reveal at/after the scene's end is never seen, and a spec without cues never grows a new warning.
The reveal times are stubbed so the test needs neither Kokoro nor a WAV."""

import pytest

from storyboard_video_mcp import config, render, spec as S

FPS = 30


def _spec(**kw):
    return {"fps": FPS, "scenes": [{"id": "a", "type": "bullets", "heading": "H", "items": ["um", "dois"],
                                    "narration": "Primeiro isto. Depois aquilo.",
                                    "cues": [{"on": "depois aquilo", "item": 1}], **kw}]}


def _tl(dur: int = 150) -> dict:  # a 5 s scene
    return {"fps": FPS, "trans": 0, "frames": dur, "scenes": [{"id": "a", "start": 0, "dur": dur}]}


@pytest.fixture
def reveal(monkeypatch):
    """Stub the per-scene, per-item reveal (frames from the scene start) cue_delays would compute."""
    def set_(frames: dict[int, int]):
        monkeypatch.setattr(render, "cue_delays", lambda spec, tl: {"a": frames})
    return set_


def test_a_cue_that_leaves_under_the_minimum_on_screen_warns(reveal):
    reveal({1: 135})  # revealed at 4.5 s of a 5 s scene: 0.5 s left
    f = render.cue_late_findings(_spec(), _tl())
    assert [(x["severity"], x["code"], x["scene"], x["item"]) for x in f] == [("warn", "cue_late", "a", 1)]
    assert f[0]["at_s"] == 4.5 and f[0]["left_s"] == 0.5
    assert "4.5s" in f[0]["message"] and "0.5s" in f[0]["message"]  # scene, item, reveal and remaining
    assert "duration_s" in f[0]["fix"]


def test_a_reveal_at_or_past_the_end_is_never_seen(reveal):
    reveal({0: 150, 1: 30})  # item 0 lands exactly on the last frame, item 1 is fine
    f = render.cue_late_findings(_spec(), _tl())
    assert [x["item"] for x in f] == [0] and f[0]["left_s"] == 0.0 and "past" in f[0]["message"]


def test_an_early_cue_is_silent_and_the_boundary_is_inclusive(reveal):
    reveal({1: 30})  # 1 s in, 4 s of screen time
    assert render.cue_late_findings(_spec(), _tl()) == []
    reveal({1: 105})  # exactly CUE_MIN_VISIBLE_S left: still a shot
    assert render.cue_late_findings(_spec(), _tl()) == []


def test_a_spec_without_cues_has_no_findings():
    legacy = {"fps": FPS, "scenes": [{"id": "a", "type": "bullets", "heading": "H", "items": ["um"],
                                      "narration": "Primeiro isto.", "duration_s": 5}]}
    assert render.cue_late_findings(legacy, render.S.timeline(S.normalize(
        {"lang": "pt-BR", "scenes": legacy["scenes"]}))) == []


def test_shot_list_carries_the_cue_late_warning(tmp_path, monkeypatch, reveal):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    reveal({1: 135})
    h = S.persist(S.normalize({"lang": "pt-BR", "fps": FPS, "scenes": _spec()["scenes"]}))
    warns = render.shot_list(h)["warnings"]
    f = [w for w in warns if w["code"] == "cue_late"]
    assert len(f) == 1 and f[0]["scene"] == "a" and f[0]["item"] == 1 and f[0]["severity"] == "warn"


def _two(**kw) -> dict:  # the same cue'd scene plus a follower, so the first one pays its transition
    s = _spec(**kw)
    return {**s, "scenes": [*s["scenes"], {"id": "b", "type": "title", "title": "Depois"}]}


def test_the_outgoing_transition_is_not_screen_time(reveal):
    """The next scene slides in over the last `trans` frames: those frames are not this scene's screen time."""
    reveal({1: 105})  # 3.5 s in: 1.5 s to the raw end, but 0.5 s of that is already the incoming scene
    tl = {"fps": FPS, "trans": 15, "frames": 285,
          "scenes": [{"id": "a", "start": 0, "dur": 150}, {"id": "b", "start": 135, "dur": 150}]}
    f = render.cue_late_findings(_two(), tl)
    assert [(x["item"], x["left_s"]) for x in f] == [(1, 1.0)]
    # the last scene is followed by nothing, so it pays no transition: the same reveal keeps its 1.5 s
    assert render.cue_late_findings(_spec(), {**_tl(150), "trans": 15}) == []
