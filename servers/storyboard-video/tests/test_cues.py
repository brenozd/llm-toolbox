"""Fase 3: cues (a bullet appears when the voice reaches its phrase).

Word timings are *estimated* (Kokoro has no timestamps), so the contract tested here is the part that
must hold: the phrase boundary follows the real pause in the WAV, a phrase said twice or not at all is
refused instead of guessed, and a spec without cues builds the page it always built.
"""
import array
import math
from pathlib import Path
import wave

import pytest

from storyboard_video_mcp import config, cues, render, spec as S, tts

SR = 24000


def speech_wav(path, parts):
    """parts = [(seconds, loud?)] -> a tone where loud, digital silence elsewhere."""
    pcm = array.array("h")
    for sec, loud in parts:
        n = int(sec * SR)
        pcm.extend(int(8000 * math.sin(2 * math.pi * 220 * i / SR)) if loud else 0 for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def test_the_phrase_boundary_follows_the_pause_in_the_wav(tmp_path):
    # "Aaa aaa. Bbb bbb bbb bbb." -- 2 words, 1 s pause, 4 words; proportional alone would cut at 1/3
    wav = speech_wav(tmp_path / "a.wav", [(0.2, False), (0.6, True), (1.0, False), (2.0, True), (0.2, False)])
    ws = cues.align("Aaa aaa. Bbb bbb bbb bbb.", wav)
    assert [w["w"] for w in ws] == ["Aaa", "aaa.", "Bbb", "bbb", "bbb", "bbb."]
    assert ws[0]["start_s"] == pytest.approx(0.2, abs=0.03)
    assert ws[1]["end_s"] == pytest.approx(0.8, abs=0.03)
    assert ws[2]["start_s"] == pytest.approx(1.8, abs=0.03)  # after the pause, not at 0.2 + 3 * 0.4
    assert ws[-1]["end_s"] == pytest.approx(3.8, abs=0.03)
    assert all(a["end_s"] <= b["start_s"] + 1e-6 for a, b in zip(ws, ws[1:]))


def test_no_pause_falls_back_to_syllables_and_empty_text_is_empty(tmp_path):
    wav = speech_wav(tmp_path / "a.wav", [(2.0, True)])
    ws = cues.align("um dois", wav)
    assert ws[0]["start_s"] == pytest.approx(0.0, abs=0.02) and ws[-1]["end_s"] == pytest.approx(2.0, abs=0.02)
    assert cues.align("   ", wav) == []


def test_find_ignores_case_accents_and_punctuation_and_reports_repeats():
    ws = [{"w": w} for w in "Rode o comando, veja o relatório e rode de novo.".split()]
    assert cues.find(ws, "VEJA o relatorio") == [3]
    assert cues.find(ws, "rode") == [0, 7]  # said twice: the caller must refuse it
    assert cues.find(ws, "nunca dito") == [] and cues.find(ws, "...") == []


def _scene(**kw):
    return {"id": "a", "type": "bullets", "heading": "H", "items": ["um", "dois"], "duration_s": 6,
            "narration": "Primeiro isto. Depois aquilo, e fim.", **kw}


def test_lint_cues():
    def codes(sc):
        return [(f["code"], f["severity"]) for f in S.lint(S.normalize({"lang": "pt-BR", "scenes": [sc]}))
                if f["code"] in ("bad_cue", "cue_unmatched", "cue_target")]
    assert codes(_scene(cues=[{"on": "depois aquilo", "item": 1}])) == []
    assert codes(_scene()) == []  # legacy spec: no cues, no findings
    assert codes(_scene(cues=[{"on": "nunca", "item": 0}])) == [("cue_unmatched", "warn")]
    assert codes(_scene(cues=[{"on": "isto", "item": 5}])) == [("bad_cue", "error")]
    assert codes(_scene(cues=[{"on": "", "item": 0}])) == [("bad_cue", "error")]
    assert codes(_scene(cues=[{"on": "isto", "item": 0, "lead_ms": "x"}])) == [("bad_cue", "error")]
    assert codes(_scene(cues="isto")) == [("bad_cue", "error")]
    assert codes({"id": "a", "type": "title", "title": "T", "duration_s": 4, "narration": "isto aqui",
                  "cues": [{"on": "isto", "item": 0}]}) == [("cue_target", "warn")]


@pytest.fixture
def narrated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)

    class Eng:  # 1 s of tone per word, 0.5 s of silence after every sentence
        def create(self, text, voice=None, lang=None, speed=1.0):
            out = []
            for w in text.split():
                out += [0.3] * int(SR * 0.6) + ([0.0] * int(SR * 0.5) if w[-1] in ".!?" else [])
            return out, SR
    monkeypatch.setattr(tts, "_engine", lambda: Eng())
    return tmp_path


def _html(sc):
    s = S.normalize({"lang": "pt-BR", "fps": 30, "scenes": [sc]})
    h = S.persist(s)
    tts.narrate(h)
    return render.build_html(S.load(h)), S.audio_manifest(S.load(h))


def test_narrate_stores_estimated_words_and_a_cue_moves_the_bullet(narrated):
    base, _ = _html(_scene())
    html, man = _html(_scene(cues=[{"on": "depois aquilo", "item": 1, "lead_ms": 100}]))
    ent = man["scenes"]["a"]
    assert ent["align"] == "estimated" and [w["w"] for w in ent["words"]][:2] == ["Primeiro", "isto."]
    start = next(w["start_s"] for w in ent["words"] if w["w"] == "Depois")
    assert f'data-d="{round((start - 0.1) * 30)}"' in html and 'data-d="18"' in base  # 8 + 1 * 10 before
    assert 'data-d="8"' in html  # item 0 untouched


def test_cues_off_switch_and_ambiguity_keep_the_fixed_stagger(narrated, monkeypatch):
    base, _ = _html(_scene())
    dup = _scene(narration="Rode isto. Rode aquilo.", cues=[{"on": "rode", "item": 1}])
    assert 'data-d="18"' in _html(dup)[0]  # said twice: refused, not guessed
    monkeypatch.setenv("STORYBOARD_CUES", "0")
    assert _html(_scene(cues=[{"on": "depois aquilo", "item": 1}]))[0].count('data-d="18"') == base.count('data-d="18"')


# --- [beat], pause_after_s, audio_lead_s ------------------------------------------------------------

def test_beat_becomes_room_tone_not_speech_and_is_not_on_screen(narrated, monkeypatch):
    calls = []
    real = tts._engine()
    monkeypatch.setattr(tts, "_engine", lambda: type("E", (), {"create": lambda self, t, **k: (calls.append(t), real.create(t, **k))[1]})())
    sc = _scene(narration="Primeiro isto [beat] depois aquilo.")
    s = S.normalize({"lang": "pt-BR", "scenes": [sc]})
    h = S.persist(s)
    tts.narrate(h)
    assert calls == ["Primeiro isto", "depois aquilo."]  # the marker never reaches the voice
    ent = S.audio_manifest(S.load(h))["scenes"]["a"]
    assert ent["duration_s"] == pytest.approx(0.6 * 4 + 0.5 + 0.45, abs=0.05)  # 4 words, the full stop's pause, the breath
    pcm = array.array("h")
    with wave.open(ent["path"], "rb") as w:
        pcm.frombytes(w.readframes(w.getnframes()))
    gap = pcm[int(SR * 1.3):int(SR * 1.55)]  # inside the breath: low-level noise, not digital silence
    assert 0 < max(abs(x) for x in gap) <= tts.ROOM_PEAK
    assert [w["w"] for w in ent["words"]] == ["Primeiro", "isto,", "depois", "aquilo."]
    assert "[beat]" not in "".join(c["text"] for c in render.narration_cues(S.load(h)))


def test_pause_after_s_lengthens_the_scene_and_bad_values_are_errors(narrated):
    def dur(**kw):
        h = S.persist(S.normalize({"lang": "pt-BR", "fps": 30, "scenes": [_scene(duration_s=1, **kw), {**_scene(), "id": "b"}]}))
        tts.narrate(h)
        return S.timeline(S.load(h))["scenes"][0]["dur"]
    assert dur(pause_after_s=0.5) - dur() == 15
    f = S.lint(S.normalize({"lang": "pt-BR", "scenes": [_scene(pause_after_s=3, audio_lead_s="x")]}))
    assert [x["code"] for x in f if x["code"] == "bad_pause"] == ["bad_pause", "bad_pause"]


def test_audio_lead_s_starts_the_voice_before_the_cut_but_not_over_the_previous_line(narrated):
    def cues_of(lead, first_lead=0):
        h = S.persist(S.normalize({"lang": "pt-BR", "fps": 30, "scenes": [
            _scene(audio_lead_s=first_lead), {**_scene(), "id": "b", "audio_lead_s": lead}]}))
        tts.narrate(h)
        spec = S.load(h)
        return spec, {c["id"]: c["start_s"] for c in render.narration_cues(spec)}
    spec, got = cues_of(0.3)
    assert got["b"] == pytest.approx(S.timeline(spec)["scenes"][1]["start"] / 30 - 0.3, abs=1e-6)
    spec, got = cues_of(0.4)  # the scene before it pays 0.4 s of tail plus the transition: still room
    end_a = got["a"] + S.audio_manifest(spec)["scenes"]["a"]["duration_s"]
    assert got["b"] >= end_a - 1e-6
    assert cues_of(0, first_lead=0.4)[1]["a"] == 0.0  # nothing before the first frame
