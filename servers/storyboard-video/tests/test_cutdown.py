"""Fase 5: cutdowns (a 60 s master yielding 30 s and 15 s cuts).

The contract is the hard part, not the arithmetic: the voice is never sped up and no line is rewritten,
so a shorter cut is only ever fewer scenes -- and the ones that go are the arc's, not the hook's or its
proof's. When the protected beats alone do not fit, the cutdown refuses with `cutdown_infeasible` and
the shortest honest duration instead of shipping a faster voice.
"""
import copy
import json

import pytest

from storyboard_video_mcp import config, cutdown, spec as S


def _sc(sid, ty="bullets", dur=6, narr="Uma linha curta aqui.", **kw):
    visual = ({"title": "Titulo"} if ty == "title" else
              {"lines": ["$ run", "ok"]} if ty == "terminal" else
              {"heading": "Titulo", "items": ["um item"]})
    return {"id": sid, "type": ty, **visual, "duration_s": dur, "narration": narr, **kw}


ROLES = {"s-hook": "hook", "s-problem": "problem", "s-cost": "implication", "s-reveal": "reveal",
         "s-value": "value", "s-value2": "value", "s-proof": "proof", "s-result": "result", "s-cta": "cta"}


def _master():
    """60 s of clock: hook 3, problem 10, implication 10, reveal 9, value 9, value 8, proof 4, result 3, cta 4."""
    return {"lang": "pt-BR", "fps": 30, "aspect": "16:9", "transition_s": 0.5,
            "direction": {"purpose": "sales-video", "scenes": {k: {"role": v} for k, v in ROLES.items()}},
            "scenes": [
                _sc("s-hook", "title", 3, "Uma hora por video."),
                _sc("s-problem", dur=10, narr="Voce grava, corta e ainda erra o ritmo no final."),
                _sc("s-cost", dur=10, narr="Cada revisao custa uma tarde inteira de trabalho."),
                _sc("s-reveal", dur=9, narr="O arranjo ja vem pronto, cena por cena, no seu terminal."),
                _sc("s-value", dur=9, narr="O roteiro vira video sem voce abrir um editor."),
                _sc("s-value2", dur=8, narr="E o mesmo script serve para o vertical e o horizontal."),
                _sc("s-proof", "terminal", 4, "Rode o comando e veja o resultado na tela."),
                _sc("s-result", dur=3, narr="Cinquenta e nove segundos, medidos."),
                _sc("s-cta", "title", 4, "Rode agora no seu repositorio."),
            ]}


def _long():
    """Every beat protected: 9 s each, so nothing can be dropped to reach 15 s."""
    roles = {"h": "hook", "p": "problem", "v": "proof", "r": "result", "c": "cta"}
    return {"lang": "pt-BR", "fps": 30, "transition_s": 0.5,
            "direction": {"purpose": "sales-video", "scenes": {k: {"role": v} for k, v in roles.items()}},
            "scenes": [_sc("h", "title", 9, "Uma hora por video."), _sc("p", dur=9),
                       _sc("v", "terminal", 9, "Rode e veja."), _sc("r", dur=9), _sc("c", "title", 9)]}


def _errors(spec):
    return [f for f in S.lint(S.normalize(spec)) if f["severity"] == "error"]


def test_master_to_30_and_15_seconds_keeps_the_arc_and_lints_clean():
    for target in (30, 15):
        res = cutdown.cutdown(_master(), target)
        assert res["before_s"] == pytest.approx(56.0, abs=0.01)  # 60 s minus the 8 transitions
        assert res["duration_s"] <= target and res["duration_s"] > 0
        assert res["duration_s"] == pytest.approx(cutdown.estimate(res["spec"], {}), abs=0.01)
        assert _errors(res["spec"]) == []
        assert [r["scene"] for r in res["removed"]]  # every removal is named, with its reason
        assert all(isinstance(r["reason"], str) and r["reason"] for r in res["removed"])
        assert S.spec_hash(res["spec"]) != S.spec_hash(S.normalize(_master()))
        # the plan travels with the scenes it plans: no dangling direction.scenes ids
        assert set(S.plan(S.normalize(res["spec"]))) == {sc["id"] for sc in res["spec"]["scenes"]}


def test_the_30s_cut_drops_cost_second_value_and_problem_first():
    res = cutdown.cutdown(_master(), 30)
    assert [r["scene"] for r in res["removed"]] == ["s-cost", "s-value2", "s-problem"]
    assert res["kept"] == ["s-hook", "s-reveal", "s-value", "s-proof", "s-result", "s-cta"]


def test_the_15s_cut_keeps_only_the_promise_its_proof_the_result_and_the_cta():
    res = cutdown.cutdown(_master(), 15)
    assert res["kept"] == ["s-hook", "s-proof", "s-result", "s-cta"]
    assert res["roles"] == {"s-hook": "hook", "s-proof": "proof", "s-result": "result", "s-cta": "cta"}
    assert res["duration_s"] == pytest.approx(12.5, abs=0.01)  # 3 + 4 + 3 + 4 minus 3 transitions


def test_hook_proof_result_cta_survive_and_no_line_is_rewritten_or_speeded_up():
    master = copy.deepcopy(S.normalize(_master()))  # snapshot before the call: cutdown must not mutate it
    res = cutdown.cutdown(master, 15)
    kept = {sc["id"]: sc for sc in res["spec"]["scenes"]}
    assert set(kept) == {"s-hook", "s-proof", "s-result", "s-cta"}
    for sc in master["scenes"]:
        if sc["id"] in kept:  # the same scene, verbatim: only whole scenes are removable
            assert kept[sc["id"]] == sc


def test_15s_is_refused_when_the_protected_beats_alone_do_not_fit():
    with pytest.raises(cutdown.CutdownError) as e:
        cutdown.cutdown(_long(), 15)
    assert isinstance(e.value, ValueError)  # the tools' guard already catches ValueError
    assert e.value.code == "cutdown_infeasible"
    assert e.value.min_s == pytest.approx(34.5, abs=0.01)  # 4 x 9 s minus 3 transitions, problem gone
    assert "cutdown_infeasible" in str(e.value) and "15" in str(e.value)


def test_cutting_the_only_beat_that_proves_the_hook_is_refused_with_its_own_code():
    spec = {"lang": "pt-BR", "transition_s": 0.5,
            "direction": {"scenes": {"h": {"role": "hook"}, "x": {"role": "problem"},
                                     "v": {"role": "value"}, "c": {"role": "cta"}}},
            "scenes": [_sc("h", "title", 4, "Uma hora por video."), _sc("x", dur=8), _sc("v", dur=12),
                       _sc("c", "title", 4, "Rode agora.")]}
    with pytest.raises(cutdown.CutdownError) as e:
        cutdown.cutdown(spec, 10)
    assert e.value.code == "hook_promise_unkept"
    assert e.value.min_s == pytest.approx(19.0, abs=0.01)  # hook + value + cta, problem gone
    assert e.value.extra["hook"] == ["h"]


def test_a_spec_without_direction_roles_is_refused_with_a_clear_error():
    legacy = {"lang": "pt-BR", "scenes": [_sc("a"), _sc("b")]}
    for spec in (legacy, {**legacy, "direction": {"purpose": "other", "scenes": {"a": {"align": "left"}}}}):
        with pytest.raises(ValueError) as e:
            cutdown.cutdown(spec, 5)
        assert e.value.code == "cutdown_needs_roles"
        assert "role" in str(e.value)


def test_a_repeated_hook_and_an_earlier_cta_are_droppable():
    roles = {"h1": "hook", "x": "problem", "h2": "hook", "v": "proof", "c1": "cta", "c2": "cta"}
    spec = {"lang": "pt-BR", "fps": 30, "transition_s": 0.5,
            "direction": {"scenes": {k: {"role": v} for k, v in roles.items()}},
            "scenes": [_sc("h1", "title", 6, "Uma hora por video."), _sc("x", dur=10),
                       _sc("h2", "title", 6, "Uma hora por video."), _sc("v", "terminal", 6, "Rode e veja."),
                       _sc("c1", "title", 4, "Rode agora."), _sc("c2", "title", 4, "Rode agora.")]}
    res = cutdown.cutdown(spec, 25)  # the role is protected, not every scene that carries it
    assert [r["scene"] for r in res["removed"]] == ["h2", "c1"]
    assert res["kept"] == ["h1", "x", "v", "c2"]
    assert "hook" in res["removed"][0]["reason"] and "cta" in res["removed"][1]["reason"]
    assert res["duration_s"] <= 25


def test_a_pre_existing_unkept_arc_does_not_block_every_drop():
    spec = {"lang": "pt-BR", "fps": 30, "transition_s": 0.5,
            "direction": {"scenes": {"h": {"role": "hook"}, "x": {"role": "problem"},
                                     "c": {"role": "cta"}}},
            "scenes": [_sc("h", "title", 6, "Uma hora por video."), _sc("x", dur=20),
                       _sc("c", "title", 4, "Rode agora.")]}
    res = cutdown.cutdown(spec, 12)  # nothing delivered the promise before the drop either: no new lie
    assert [r["scene"] for r in res["removed"]] == ["x"]
    assert res["kept"] == ["h", "c"] and res["duration_s"] <= 12
    with pytest.raises(cutdown.CutdownError) as e:  # too short is still refused, but as infeasible
        cutdown.cutdown(spec, 5)
    assert e.value.code == "cutdown_infeasible"


def test_the_cutdown_says_whether_its_seconds_are_a_master_estimate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    roles = {"h": "hook", "p": "problem", "v": "proof", "c": "cta"}
    master = S.normalize({"lang": "pt-BR", "fps": 30, "transition_s": 0.5,
                          "direction": {"scenes": {k: {"role": r} for k, r in roles.items()}},
                          "scenes": [_sc("h", "title", 3, "Uma hora por video."), _sc("p", dur=3),
                                     _sc("v", "terminal", 3, "Rode e veja."), _sc("c", "title", 3)]})
    man = tmp_path / "audio" / S.spec_hash(master) / "manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"scenes": {sid: {"duration_s": 5.0} for sid in roles}}))  # a slower voice
    res = cutdown.cutdown(master, 17)
    assert res["duration_basis"] == "master"  # this hash has no /audio dir yet: the master's WAVs price it
    assert res["duration_s"] == pytest.approx(2 * (5.0 + S.AUDIO_TAIL + 0.5) + (5.0 + S.AUDIO_TAIL) - 2 * 0.5, abs=0.01)
    own = tmp_path / "audio" / S.spec_hash(res["spec"]) / "manifest.json"
    own.parent.mkdir(parents=True)
    own.write_text(json.dumps({"scenes": {sid: {"duration_s": 2.0} for sid in res["kept"]}}))
    again = cutdown.cutdown(master, 17)
    assert S.spec_hash(again["spec"]) == S.spec_hash(res["spec"])  # the same cut, priced from its own WAVs
    assert again["duration_basis"] == "spec"
    assert again["duration_s"] == pytest.approx(3 * 3.0 - 2 * 0.5, abs=0.01)


def test_a_target_already_met_removes_nothing():
    res = cutdown.cutdown(_master(), 90)
    assert res["removed"] == [] and res["duration_s"] == pytest.approx(56.0, abs=0.01)
    assert res["kept"] == [sc["id"] for sc in _master()["scenes"]]


def test_estimate_budgets_the_read_time_and_prefers_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    s = S.normalize({"lang": "pt-BR", "transition_s": 0.0,
                     "scenes": [_sc("a", dur=3, narr=" ".join(["palavra"] * 16))]})
    # 16 words / READ_WPS + the tail: the line does not fit in the 3 s the spec asked for
    assert cutdown.estimate(s) == pytest.approx(16 / S.READ_WPS + S.AUDIO_TAIL, abs=0.01)
    man = tmp_path / "audio" / S.spec_hash(s) / "manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"scenes": {"a": {"duration_s": 7.0}}}))
    assert cutdown.estimate(s) == pytest.approx(7.0 + S.AUDIO_TAIL, abs=0.01)  # the WAV is the clock


def test_a_cutdown_prices_the_kept_lines_with_the_master_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    master = S.normalize(_master())
    h = S.spec_hash(master)
    man = tmp_path / "audio" / h / "manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"scenes": {sid: {"duration_s": 12.0} for sid in ROLES}}))  # a slower voice
    assert cutdown.estimate(master) == pytest.approx(9 * 12.4, abs=0.01)  # nine lines of 12 s + tail
    with pytest.raises(cutdown.CutdownError) as e:  # the budget is the voice's, not scene.duration_s
        cutdown.cutdown(master, 15)
    assert e.value.code == "cutdown_infeasible"
    assert e.value.min_s == pytest.approx(4 * 12.4, abs=0.01)  # hook + proof + result + cta
    assert cutdown.cutdown(master, 60)["duration_s"] == pytest.approx(4 * 12.4, abs=0.01)
