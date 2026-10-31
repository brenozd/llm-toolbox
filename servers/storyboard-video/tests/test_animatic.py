"""Fase 2: the rough cut (scratch VO + animatic + shot list).

What this file defends:
- `narrate(scratch=True)` labels the manifest and **never** moves the final `resolved_hash` (the label is
  metadata, not a cache key): a scratch pass and a delivery pass share the WAVs, and the delivery id is
  the same before and after the label is written;
- the pace map is measured from the WAVs of *known* duration, not from `duration_s` -- including a silent
  scene, which has no line and therefore holds the picture for its whole length;
- the animatic is a *profile* of the delivery render (360p, 15 fps, ANIMATIC watermark, no capture, no
  music) with its own hash stage and a path outside `out/<resolved_hash>/`;
- `shot_list` says what to capture and how long the voice leaves for it.

Synthetic WAVs are written directly into `/work/audio/<spec_hash>/manifest.json`, so the pacing tests need
neither Pocket TTS nor ffmpeg. The end-to-end render skips on a host without chromium/ffmpeg.
"""

import array
import asyncio
import inspect
import json
import math
import shutil
import wave
from pathlib import Path

import pytest

from storyboard_video_mcp import config, render, server, spec as S, tts


class FakeEngine:
    """Stand-in for Pocket TTS: 0.05 s of audio per character (deterministic, no model)."""

    def __init__(self):
        self.calls = []

    def create(self, text, voice=None, lang=None):
        self.calls.append({"text": text, "voice": voice, "lang": lang})
        return [0.0] * int(24000 * 0.05 * len(text)), 24000


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    eng = FakeEngine()
    monkeypatch.setattr(tts, "_engine", lambda: eng)
    return tmp_path, eng


def _wav(path: Path, seconds: float, sr: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(array.array("h", [0] * int(seconds * sr)).tobytes())


def write_manifest(spec: dict, durs: dict[str, float], scratch: bool = False) -> dict:
    """A narration manifest with WAVs of *known* duration: the timeline and the pace map believe the files."""
    d = config.WORK / "audio" / S.spec_hash(spec)
    scenes = {}
    for sid, sec in durs.items():
        p = d / f"{sid}-{sid}.wav"
        _wav(p, sec)
        scenes[sid] = {"key": sid, "path": str(p), "duration_s": round(sec, 3), "text": "x"}
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({"spec_hash": S.spec_hash(spec), "lang": spec.get("lang"),
                                                 "scratch": scratch, "scenes": scenes}))
    return scenes


# --- scratch VO -------------------------------------------------------------------------------------

def test_scratch_labels_the_manifest_and_never_moves_the_final_hash(work):
    """The point of a scratch pass is that it is the *same* voice: the WAVs are reused and the delivery
    id does not move. Only the label (and the animatic's own stage id) tells the two apart."""
    _, eng = work
    s = S.normalize({"lang": "pt-BR", "scenes": [
        {"id": "a", "type": "title", "title": "Oi", "narration": "Olá, mundo.", "duration_s": 3}]})
    h = S.persist(s)
    before = S.resolved_hash(S.load(h))
    r = tts.narrate(h, scratch=True)
    assert r["scratch"] is True and r["synthesized"] == 1
    man = S.audio_manifest(S.load(h))
    assert man["scratch"] is True and man["scenes"]["a"]["duration_s"] > 0
    after = S.resolved_hash(S.load(h))
    digest_before = S.audio_digest(S.load(h))
    assert after != before  # the *speech* is what changed the id: the manifest now has a WAV
    assert S.resolved_hash(S.load(h), stage="animatic") != after  # a rough cut is a different object
    # the label itself is not in the hash: flipping it leaves the delivery id alone
    (config.WORK / "audio" / S.spec_hash(S.load(h)) / "manifest.json").write_text(
        json.dumps({**man, "scratch": False}))
    assert S.resolved_hash(S.load(h)) == after
    assert S.audio_digest(S.load(h)) == digest_before  # the label is not part of the digest
    # and the final pass pays no second synthesis: same text, same voice, same cache key
    fin = tts.narrate(h)
    assert fin["scratch"] is False and fin["synthesized"] == 0 and fin["cached"] == 1
    assert len(eng.calls) == 1
    assert S.audio_manifest(S.load(h))["scratch"] is False
    assert S.resolved_hash(S.load(h)) == after


# --- pace map ---------------------------------------------------------------------------------------

def test_pace_map_is_measured_from_the_wavs_including_a_silent_scene(work):
    s = S.normalize({"lang": "en", "fps": 30, "scenes": [
        {"id": "a", "type": "title", "title": "A", "narration": "one two three", "duration_s": 3},
        {"id": "b", "type": "bullets", "heading": "B", "items": ["x"], "duration_s": 4},
        {"id": "c", "type": "title", "title": "C", "narration": "four five", "duration_s": 3}]})
    spec = S.normalize(s)
    write_manifest(spec, {"a": 2.0, "c": 1.5})
    tl = S.timeline(spec)
    pm = {r["id"]: r for r in render.pace_map(spec)["scenes"]}
    # the scenes are the timeline's, in seconds (fps 30, 0.5 s transition)
    assert [round(t["dur"] / 30, 3) for t in tl["scenes"]] == [pm[i]["dur_s"] for i in ("a", "b", "c")]
    # a narrated scene: words/wps from the line, the head is covered by the stretch, the tail is the room
    assert pm["a"]["words"] == 3 and pm["a"]["wps"] == 1.5 and pm["a"]["voice_s"] == 2.0
    assert pm["a"]["lead_s"] == 0.0 and pm["a"]["tail_s"] == 1.0
    # a silent scene: no line, so the whole card is the hold
    assert pm["b"]["words"] == 0 and pm["b"]["wps"] == 0.0 and pm["b"]["voice_s"] == 0.0
    assert pm["b"]["lead_s"] == 0.0 and pm["b"]["tail_s"] == pm["b"]["dur_s"] == 4.0
    # the last scene pays no transition, so its tail is audio-tail only
    assert pm["c"]["tail_s"] == round(pm["c"]["dur_s"] - 1.5, 3) == 1.5
    assert "more regular" in render.pace_map(spec)["caveat"]
    assert render.pace_map(spec)["words"] == 5


# --- the animatic profile ---------------------------------------------------------------------------

def test_the_animatic_is_a_profile_of_the_delivery_render():
    spec = S.normalize({"fps": 30, "scenes": [
        {"id": "a", "type": "title", "title": "Hi", "duration_s": 4},
        {"id": "b", "type": "terminal", "title": "mint", "lines": ["$ ls"], "duration_s": 2}]})
    tl = S.timeline(spec)
    atl = render.animatic_timeline(tl)
    assert render.ANIMATIC["fps"] == atl["fps"] == 15 and render.ANIMATIC["short_side"] == 360
    assert atl["trans"] == 0  # a card needs no crossfade
    for o, a in zip(tl["scenes"], atl["scenes"]):  # same seconds: the delivery's cues still line up
        assert abs(a["start"] / 15 - o["start"] / 30) <= 1 / 15
        assert abs(a["dur"] / 15 - o["dur"] / 30) <= 1 / 15
    assert render.animatic_size(spec) == (640, 360)
    assert render.animatic_size(S.normalize({**spec, "aspect": "9:16"})) == (360, 640)
    cards = render.animatic_cards(spec, tl)
    assert cards["fps"] == 15 and cards["music"] is None and cards["transition_s"] == 0
    assert all(sc["type"] == "bullets" for sc in cards["scenes"])
    assert not any(k in sc for sc in cards["scenes"] for k in ("video", "image", "capture_id"))
    assert "[capture: terminal session: mint" in cards["scenes"][1]["items"][0]
    html = render.build_html(cards, atl, render.ANIMATIC["watermark"], (640, 360))
    assert "ANIMATIC" in html and "F=15" in html and 'class="wm"' in html
    assert "F=30" in render.build_html(spec) and "ANIMATIC" not in render.build_html(spec)


def test_the_placeholder_follows_the_spec_language():
    spec = S.normalize({"lang": "pt-BR", "scenes": [
        {"id": "a", "type": "terminal", "heading": "demo", "lines": ["$ ls"], "duration_s": 6}]})
    cards = render.animatic_cards(spec, S.timeline(spec))
    card = cards["scenes"][0]
    assert card["items"][0] == "[captura: sessão de terminal: demo — 6.0s]"
    assert card["heading"] == "terminal · demo"


def test_the_rough_cut_is_named_and_placed_outside_the_delivery(work):
    tmp, _ = work
    spec = S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi", "duration_s": 4}]})
    p = render.animatic_path(spec)
    assert p.name.endswith("_ANIMATIC.mp4") and p.parent == tmp / "animatic"
    assert (tmp / "out") not in p.parents
    assert S.resolved_hash(spec, stage="animatic") != S.resolved_hash(spec)
    assert S.resolved_hash(spec) == S.resolved_hash(spec, stage="")  # the default stage adds nothing


# --- shot list --------------------------------------------------------------------------------------

def test_shot_list_says_what_to_capture_and_the_time_the_voice_left(work):
    s = S.normalize({"lang": "en", "fps": 30, "scenes": [
        {"id": "hook", "type": "title", "title": "Leaks", "narration": "one two", "duration_s": 3},
        {"id": "term", "type": "terminal", "heading": "run", "narration": "three four five", "duration_s": 2},
        {"id": "code", "type": "code", "code": "free(p);", "source": "leak.c", "narration": "six seven",
         "duration_s": 2, "evidence": "README.md:20-24"}]})
    h = S.persist(s)
    write_manifest(S.load(h), {"hook": 1.0, "term": 1.5, "code": 1.0})
    r = render.shot_list(h)
    rows = {x["id"]: x for x in r["scenes"]}
    assert r["captures_needed"] == 1  # the title needs none, and the inline code scene already has its text
    assert rows["hook"]["need"] is None and rows["hook"]["tool"] is None
    assert rows["term"]["need"] and rows["term"]["tool"] == "capture_terminal_session"
    assert rows["term"]["have"] is None
    # the time the voice left, from the manifest (2.4 s scene, 1.5 s line): the shot gets 0.9 s
    assert rows["term"]["dur_s"] == 2.4 and rows["term"]["voice_s"] == 1.5 and rows["term"]["hold_s"] == 0.9
    assert rows["code"]["have"] == "code" and rows["code"]["tool"] is None and rows["code"]["evidence"] == "README.md:20-24"
    assert rows["code"]["call"] == {"tool": "extract_code", "args": {"path": "README.md", "lines": "20-24"}}
    # warn only: a shot the voice leaves under a second on screen is a flash
    assert [w["code"] for w in r["warnings"]] == ["shot_no_hold"] and r["warnings"][0]["scene"] == "term"
    assert r["status"] == "ok" and r["duration_s"] > 0


def test_shot_list_flags_an_already_captured_scene(work):
    s = S.normalize({"lang": "en", "scenes": [
        {"id": "t", "type": "terminal", "video": "/work/captures/x/take.mp4", "duration_s": 6}]})
    h = S.persist(s)
    row = render.shot_list(h)["scenes"][0]
    assert row["have"] == "video" and row["need"] is None and row["tool"] is None
    assert render.shot_list(h)["captures_needed"] == 0


# --- tool registration ------------------------------------------------------------------------------

def test_the_new_tools_are_registered_and_narrate_takes_scratch():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"animatic", "shot_list"} <= names and {"narrate", "render", "stills"} <= names
    assert inspect.signature(server.narrate).parameters["scratch"].default is False
    assert "scratch" in inspect.signature(tts.narrate).parameters


# --- the whole path (needs chromium + ffmpeg) --------------------------------------------------------

def _renderable() -> bool:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(args=render.ARGS, executable_path=config.chromium()).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _renderable(), reason="needs ffmpeg and chromium to render the rough cut")
def test_a_rough_cut_renders_at_360p15_with_its_pace_map(work, monkeypatch):
    tmp, _ = work

    class ToneEngine:  # a real tone: loudnorm has nothing to measure on digital silence
        def create(self, text, voice=None, lang=None):
            n = int(24000 * 0.05 * len(text))
            return [0.1 * math.sin(2 * math.pi * 220 * i / 24000) for i in range(n)], 24000

    monkeypatch.setattr(tts, "_engine", lambda: ToneEngine())
    s = S.normalize({"lang": "en", "fps": 30, "scenes": [
        {"id": "a", "type": "title", "title": "Rough", "narration": "one two", "duration_s": 2},
        {"id": "b", "type": "bullets", "heading": "Two", "items": ["x"], "narration": "three", "duration_s": 2}]})
    h = S.persist(s)
    tts.narrate(h, scratch=True)
    r = render.render_sync(h, "animatic", {})  # the delivery entry point, animatic profile
    assert r["quality"] == "animatic"
    p = Path(r["video"])
    assert p.is_file() and p.name.endswith("_ANIMATIC.mp4") and (tmp / "out") not in p.parents
    pr = render._probe(str(p))
    assert (pr["width"], pr["height"]) == (640, 360) and round(pr["fps"]) == 15
    assert abs(pr["duration"] - r["duration_s"]) < 0.2
    assert [x["id"] for x in r["pace_map"]["scenes"]] == ["a", "b"] and r["audio"] is True
    assert p.with_suffix(".json").is_file()
    assert not list((tmp / "out").glob("*/delivery.mp4"))  # a rough cut never writes a delivery


def test_animatic_tool_is_a_background_job_and_cuts_do_not_share_scratch_files(work, monkeypatch):
    import asyncio
    from storyboard_video_mcp import server
    seen = []
    monkeypatch.setattr(render, "start", lambda h, q: seen.append((h, q)) or "job1")
    h = S.persist(S.normalize({"lang": "en", "fps": 30, "scenes": [{"id": "a", "type": "title", "title": "T", "duration_s": 2}]}))
    got = asyncio.run(server.animatic(h))
    assert got == {"status": "ok", "job_id": "job1"} and seen == [(h, "animatic")]


def test_shot_list_survives_a_malformed_plan_entry_and_flags_a_missing_voice(work, monkeypatch):
    s = S.normalize({"lang": "en", "fps": 30, "scenes": [
        {"id": "a", "type": "title", "title": "T", "narration": "one two three", "duration_s": 3}],
        "direction": {"purpose": "other", "scenes": {"a": {"role": "hook"}}}})
    h = S.persist(s)
    write_manifest(S.load(h), {})  # narrated, never synthesised
    pm = render.pace_map(S.load(h))["scenes"][0]
    assert pm["voice_missing"] is True and pm["tail_s"] == 0.0
    monkeypatch.setattr(S, "plan", lambda spec: {"a": "oops"})  # a non-dict entry must not raise
    row = render.shot_list(h)["scenes"][0]
    assert row["id"] == "a" and row["role"] is None
