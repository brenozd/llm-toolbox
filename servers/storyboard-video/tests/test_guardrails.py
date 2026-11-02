"""Guard-rails and spec contract: unknown tool arguments, dense captures, duration 'auto', intent, schema, patch_spec, TTS reuse."""
import asyncio
import json

from storyboard_video_mcp import config, patch, server, spec as S, spec_schema, tts


def _spec(**sc):
    return {"scenes": [{"id": "a", "type": "title", "title": "T", **sc}]}


def _call(name, args):
    r = asyncio.run(server.mcp.call_tool(name, args))
    return json.loads(r[0].text)


def test_unknown_argument_is_an_error():
    out = _call("render", {"spec_hash": "x", "profile": "delivery"})
    assert out["status"] == "error" and "profile" in out["message"] and "quality" in out["message"]


def test_dense_capture_warns_on_wide_lines():
    s = S.normalize({"scenes": [{"id": "t", "type": "terminal", "lines": ["x" * 80]}]})
    assert "dense_capture" in {f["code"] for f in S.lint(s)}
    s = S.normalize({"scenes": [{"id": "t", "type": "terminal", "lines": ["cpu 12%"]}]})
    assert "dense_capture" not in {f["code"] for f in S.lint(s)}


def test_duration_auto_resolves_to_a_clamped_number():
    s = S.normalize(_spec(duration_s="auto", narration="word " * 100))
    assert s["scenes"][0]["duration_s"] == 12.0
    s = S.normalize(_spec(duration_s="auto"))
    assert s["scenes"][0]["duration_s"] == 1.5
    assert not [f for f in S.lint(s) if f["code"] == "duration"]


def test_intent_shape_and_strict_mode():
    ok = {"sees": "a chart", "understands": "it grew"}
    assert "bad_intent" not in {f["code"] for f in S.lint(S.normalize(_spec(intent=ok)))}
    assert "bad_intent" in {f["code"] for f in S.lint(S.normalize(_spec(intent={"sees": "x"})))}
    strict = {**_spec(), "direction": {"strict_intent": True}}
    assert "missing_intent" in {f["code"] for f in S.lint(S.normalize(strict))}


def test_schema_tracks_code_constants():
    sc = spec_schema.schema()["properties"]["scenes"]["items"]["properties"]
    assert set(sc["type"]["enum"]) == S.TYPES


def test_patch_spec_remove_move_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    base = {"scenes": [{"id": "a", "type": "title", "title": "A"}, {"id": "b", "type": "title", "title": "B"}],
            "direction": {"scenes": {"a": {"role": "hook"}, "b": {"role": "cta"}}}}
    h = S.persist(S.normalize(base))
    out = patch.apply(h, [{"op": "remove", "scene": "a"}, {"op": "replace", "scene": "b", "field": "title", "value": "B2"}])
    assert out["status"] == "ok" and out["diff"] == ["- scene a", "~ b.title"]
    assert out["new_spec_hash"] != h
    done = patch.apply(h, [{"op": "remove", "scene": "a"}], dry_run=False)
    assert "a" not in S.load(done["new_spec_hash"])["direction"]["scenes"]
    assert S.load(h)["scenes"][0]["id"] == "a"  # the original is untouched


def test_tts_reuses_a_wav_with_the_same_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    key = tts.cache_key("hello", "alba", "en")
    old = tmp_path / "audio" / "oldhash"
    old.mkdir(parents=True)
    (old / f"a-{key}.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(tts, "_engine", lambda: (_ for _ in ()).throw(AssertionError("must not synthesize")))
    monkeypatch.setattr(tts, "wav_seconds", lambda p: 1.0)
    monkeypatch.setattr(tts, "words_of", lambda *a, **k: [])
    monkeypatch.setattr(tts, "_voice_of", lambda *a: "alba")
    h = S.persist(S.normalize({"lang": "en", "scenes": [{"id": "a", "type": "title", "title": "T", "narration": "hello"}]}))
    out = tts.narrate(h)
    assert out["synthesized"] == 0 and (tmp_path / "audio" / h / f"a-{key}.wav").exists()
