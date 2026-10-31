import json
import wave

import pytest

from storyboard_video_mcp import config, spec as S, tts, voices


class FakeEngine:
    """Stand-in for Pocket TTS: 0.05 s of audio per character, records every call."""

    def __init__(self):
        self.calls = []

    def create(self, text, voice=None, lang=None):
        self.calls.append({"text": text, "voice": voice, "lang": lang})
        return [0.0] * int(24000 * len(text) * 0.05), 24000


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    eng = FakeEngine()
    monkeypatch.setattr(tts, "_engine", lambda: eng)
    return tmp_path, eng


def mk(**kw):
    return S.normalize({"lang": "pt-BR", "scenes": [{"id": "a", "type": "title", "title": "Oi",
                                                     "narration": "Olá, mundo.", "duration_s": 3}], **kw})


def test_one_wav_per_scene_with_real_durations(work):
    _, eng = work
    s = mk(scenes=[{"id": "a", "type": "title", "title": "Oi", "narration": "Olá, mundo.", "duration_s": 3},
                   {"id": "b", "type": "title", "title": "Silêncio", "duration_s": 3}])
    r = tts.narrate(S.persist(s))
    assert r["status"] == "ok" and r["synthesized"] == 1 and [x["id"] for x in r["scenes"]] == ["a"]
    man = S.audio_manifest(s)
    sc = man["scenes"]["a"]
    assert sc["duration_s"] > 0 and sc["lang"] == "pt-BR" and sc["voice"] == "rafael"
    with wave.open(sc["path"], "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - sc["duration_s"]) < 1e-3
    assert eng.calls[0]["lang"] == "portuguese"


def test_say_is_applied_before_synthesis(work):
    _, eng = work
    s = mk(say={"LD_PRELOAD": "el di preload"},
           scenes=[{"id": "a", "type": "title", "title": "x", "narration": "Ligue o LD_PRELOAD.", "duration_s": 3}])
    tts.narrate(S.persist(s))
    assert eng.calls[0]["text"] == "Ligue o el di preload."
    assert S.audio_manifest(s)["scenes"]["a"]["text"] == "Ligue o el di preload."


def test_say_keys_must_match_the_token_exactly(work):
    """pronounce() is case-sensitive, so a lowercased key would lint clean and change nothing:
    the lint must flag it and the fix must spell the key as the token appears."""
    _, eng = work
    s = mk(say={"ld_preload": "el di preload"},
           scenes=[{"id": "a", "type": "title", "title": "x", "narration": "Ligue o LD_PRELOAD.", "duration_s": 3}])
    f = [x for x in S.lint(S.normalize(s)) if x["code"] == "say_missing"]
    assert [x["message"] for x in f] == ["'LD_PRELOAD' will be read by the TTS engine"]
    assert "spec.say['LD_PRELOAD']" in f[0]["fix"]
    tts.narrate(S.persist(s))
    assert eng.calls[0]["text"] == "Ligue o LD_PRELOAD."  # the audio really is unchanged
    s["say"] = {"LD_PRELOAD": "el di preload"}
    assert not [x for x in S.lint(S.normalize(s)) if x["code"] == "say_missing"]
    assert tts.pronounce("Ligue o LD_PRELOAD.", s["say"]) == "Ligue o el di preload."


def test_cache_reuses_and_a_new_voice_is_a_new_file(work):
    tmp, eng = work
    h = S.persist(mk(lang="en"))
    a = tts.narrate(h)
    b = tts.narrate(h)
    assert b["synthesized"] == 0 and b["cached"] == 1 and len(eng.calls) == 1
    assert a["scenes"][0]["path"] == b["scenes"][0]["path"]
    h2 = S.persist(mk(lang="en", voice="marius"))
    c = tts.narrate(h2)
    assert c["scenes"][0]["key"] != a["scenes"][0]["key"] and eng.calls[-1]["voice"] == "marius"
    assert len(list((tmp / "audio" / h2).glob("*.wav"))) == 1


def test_timeline_stretches_a_scene_to_fit_its_audio(work):
    s = mk(scenes=[{"id": "a", "type": "title", "title": "x", "narration": "u" * 100, "duration_s": 3}])
    assert S.timeline(s)["frames"] == 3 * 30
    tts.narrate(S.persist(s))  # 100 chars -> 5.0 s of audio
    tl = S.timeline(s)
    # the scene pays for the tail only: it is the last one, so no transition follows it to overlap it
    assert tl["scenes"][0]["dur"] == round((5.0 + S.AUDIO_TAIL) * 30)


def test_resolved_hash_follows_the_speech(work):
    h = S.persist(mk())
    before = S.resolved_hash(S.load(h))
    tts.narrate(h)
    after = S.resolved_hash(S.load(h))
    assert before != after
    tts.narrate(h)  # same speech, same WAVs: nothing to invalidate
    assert S.resolved_hash(S.load(h)) == after
    h2 = S.persist(mk(scenes=[{"id": "a", "type": "title", "title": "Oi", "narration": "Olá, Brasil.",
                               "duration_s": 3}]))
    tts.narrate(h2)
    assert S.resolved_hash(S.load(h2)) != after


def test_cache_key_and_resolved_hash_track_the_model_and_the_template(work, monkeypatch, tmp_path):
    model = tmp_path / "pocket-tts"
    model.write_bytes(b"x" * 100)
    monkeypatch.setattr(config, "MODEL", model)
    a = tts.cache_key("hi", "george", "en")
    h1 = S.resolved_hash(mk())
    model.write_bytes(b"x" * 200)  # same name, different model: no WAV may be reused
    assert tts.cache_key("hi", "george", "en") != a
    assert S.resolved_hash(mk()) != h1
    h = S.resolved_hash(mk())
    monkeypatch.setattr(config, "RENDER_VERSION", "999")  # a template change invalidates stills too
    assert S.resolved_hash(mk()) != h


def test_catalogue_voice_is_required_and_speed_is_refused():
    def codes(**kw):
        return {f["code"] for f in S.lint(mk(**kw))}

    assert "bad_voice" in codes(voice="pf_dora") and "bad_voice" not in codes(voice="rafael") and "bad_voice" in codes(voice="marius")  # pt-BR: rafael only
    assert "speed_unsupported" in codes(speed=1.1)
    assert "bad_voice" in {f["code"] for f in S.lint(mk(scenes=[{"id": "a", "type": "title", "title": "x",
                                                                 "narration": "Oi.", "duration_s": 3, "voice": "jean"}]))}


def test_suggest_voices_ranks_by_the_answers():
    top = lambda lang, **a: [p["voice"] for p in voices.suggest(lang, 19, **a)["picks"]]
    assert top("en", pace="fast")[0] == "marius" and top("en", emotion="expressive")[0] == "marius"
    assert top("en", emotion="calm", pitch="low")[0] in {"charles", "javert", "michael"}
    assert top("pt-BR")[0] == "rafael" and "jean" not in top("en") and "rafael" not in top("en")
    assert voices.suggest("en", pace="normal")["picks"][0]["voice"] == "michael"  # the median pace of the catalogue
    r = voices.suggest("pt-BR", 1, flow="smooth", pitch="low")
    assert [p["voice"] for p in r["picks"]] == ["rafael"] and voices.names("pt-BR") == ["rafael"] and "NOT measured" in r["caveat"]
    p = voices.suggest("en", 2, flow="smooth")["picks"]
    assert len(p) == 2 and p[0]["fit"] >= p[1]["fit"]
    with pytest.raises(ValueError):
        voices.suggest("en", pace="warp")
    with pytest.raises(ValueError):
        voices.suggest("fr")


def test_engine_calls_the_binary_offline(tmp_path, monkeypatch):
    fake = tmp_path / "pocket-tts"
    fake.write_text("#!/bin/sh\n# args: generate -q --language L --voice V --text T --output-path P\n"
                    "echo \"$@\" > " + str(tmp_path / "argv") + "\n"
                    "echo \"$HF_HUB_OFFLINE\" > " + str(tmp_path / "offline") + "\n"
                    "exec cp " + str(tmp_path / "in.wav") + " \"${10}\"\n")
    fake.chmod(0o755)
    _write = tts._write_wav
    _write(tmp_path / "in.wav", [0.5] * 2400, 24000)
    monkeypatch.setattr(config, "MODEL", fake)
    samples, sr = tts.Engine().create("Oi.", voice="marius", lang="portuguese")
    assert sr == 24000 and len(samples) == 2400 and abs(samples[0] - 0.5) < 1e-3
    assert "--language portuguese --voice marius --text Oi." in (tmp_path / "argv").read_text()
    assert (tmp_path / "offline").read_text().strip() == "1"
    fake.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
    with pytest.raises(RuntimeError, match="boom"):
        tts.Engine().create("x", voice="marius", lang="english")


def test_narrate_needs_a_lang(work):
    s = mk()
    del s["lang"]
    with pytest.raises(ValueError):
        tts.narrate(S.persist(s))


def test_lint_narration_language_and_say():
    def codes(s):
        return {f["code"] for f in S.lint(S.normalize(s))} - {"no_direction"}  # every spec without a direction warns; not what this test is about

    assert codes({"scenes": [{"id": "a", "type": "title", "title": "x", "narration": "Oi"}]}) == {"missing_lang"}
    assert "bad_lang" in codes({"lang": "fr", "scenes": [{"id": "a", "type": "title", "title": "x"}]})
    assert "bad_say" in codes({"lang": "en", "say": ["x"], "scenes": [{"id": "a", "type": "title", "title": "x"}]})
    spoken = {"lang": "en", "scenes": [{"id": "a", "type": "code", "code": "malloc(1);", "source": "m.c",
                                        "narration": "Call LD_PRELOAD and malloc here", "duration_s": 3}]}
    assert codes(spoken) == {"say_missing"}
    assert codes({**spoken, "say": {"LD_PRELOAD": "el di preload", "malloc": "maloc"}}) == set()


def test_lint_narration_pace_and_uncited_numbers():
    s = {"lang": "en", "scenes": [{"id": "a", "type": "title", "title": "x", "duration_s": 3,
                                   "narration": "one two three four five six seven eight nine ten eleven twelve thirteen"}]}
    assert "narration_pace" in {f["code"] for f in S.lint(S.normalize(s))}
    s["scenes"][0]["narration"] = "it is 40% faster"
    assert "uncited_stat" in {f["code"] for f in S.lint(S.normalize(s))}
    s["scenes"][0]["evidence"] = "README.md:3"
    assert "uncited_stat" not in {f["code"] for f in S.lint(S.normalize(s))}


def test_phonetic_spelling_in_narration_is_an_error():
    spec = {"lang": "en", "say": {"LD_PRELOAD": "L D preload"}, "scenes": [
        {"id": "a", "type": "title", "title": "t", "duration_s": 6, "narration": "It uses L D preload."}]}
    assert any(x["code"] == "phonetic_in_narration" for x in S.lint(S.normalize(spec)))


def test_container_path_on_screen_warns():
    spec = {"lang": "en", "scenes": [{"id": "a", "type": "title", "title": "/work/leak.c", "duration_s": 5}]}
    assert any(x["code"] == "container_path" for x in S.lint(S.normalize(spec)))


def test_narrate_refuses_a_voice_outside_the_catalogue():
    for bad in ("pf_dora", "jean", "rafael"):  # old Kokoro name, CC BY-NC, pt-only voice in an en spec
        sp = mk(lang="en", voice=bad)
        with pytest.raises(ValueError, match="catalogue voice"):
            tts._voice_of(sp, sp["scenes"][0])
    assert "bad_voice" in {f["code"] for f in S.lint(mk(lang="en", voice="rafael"))}
    assert "bad_voice" in {f["code"] for f in S.lint(mk(voice=["marius"]))}  # unhashable: a finding, not a traceback


def test_suggest_ties_and_n():
    assert len(voices.suggest("en", 99)["picks"]) == 19
    for n in (0, -1, True):
        with pytest.raises(ValueError):
            voices.suggest("en", n)
    assert voices.suggest("pt-BR")["picks"][0]["f0_hz"] == 152


def test_cc_by_voice_is_credited():
    from storyboard_video_mcp import audio
    sp = mk(lang="en", voice="george")
    txt = audio.credits_text(sp)
    assert "Voice credits" in txt and '"george"' in txt and "CC BY 4.0" in txt
    assert audio.credits_text(mk(lang="en", voice="marius")) is None  # CC0: nothing owed
    assert audio.credits_text(mk(lang="en", voice="alba")).count("Alba MacKenna") == 1
