import importlib.util
import json
import sys
from pathlib import Path

import pytest

from promo_video_mcp import music, spec as S

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_music.py"


@pytest.fixture(scope="module")
def fm():
    """scripts/ is not a package: load fetch_music.py by path."""
    spec = importlib.util.spec_from_file_location("fetch_music", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_music"] = mod
    spec.loader.exec_module(mod)
    return mod


def mk(**kw):
    return S.normalize({"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw})


def codes(s):
    return {f["code"] for f in S.lint(s)}


def test_catalog_is_cc0_or_pd_and_complete():
    cat = music.catalog()
    assert cat["tracks"], "run scripts/fetch_music.py to populate music/catalog.json"
    for t in cat["tracks"]:
        assert t["license"] in {"CC0", "PD"}, t["id"]
        assert t["source_url"].startswith("https://") and len(t["sha256"]) == 64
        assert t["mood"] and t["duration_s"] > 0 and t["title"] and t["artist"]


def test_list_music_filters_by_mood():
    calm = music.list_music("calm")["tracks"]
    assert [t["id"] for t in calm] == ["moonlight-sonata"]
    assert "epic" in music.list_music()["moods"]
    assert music.get("moonlight-sonata")["license"] == "PD"
    assert music.get("nope") is None


def test_credit_file_only_lists_attribution_tracks(fm):
    pd = {"id": "a", "license": "PD", "title": "A", "artist": "X", "attribution_required": False,
          "attribution": ""}
    by = {"id": "b", "license": "CC0", "title": "B", "artist": "Y", "attribution_required": True,
          "attribution": "B by Y, CC0"}
    assert fm.credits([pd]) == ""  # nothing to credit -> no CREDITS.txt at all
    text = fm.credits([pd, by])
    assert "B by Y, CC0" in text and "A by" not in text


def test_fetch_music_refuses_a_cc_by_entry(fm, tmp_path, monkeypatch):
    """The bundle is CC0/PD only: a CC-BY track must be rejected before a byte is downloaded."""
    cc_by = {"id": "nope", "file": "nope.ogg", "title": "T", "artist": "A", "license": "CC BY 4.0",
             "license_note": "", "source_url": "https://example.org/t", "sha256": "0" * 64,
             "mood": ["calm"], "duration_s": 10.0, "attribution": "T by A, CC BY 4.0"}
    for raw in ("CC BY 4.0", "CC-BY-SA 4.0", "OGA-BY 3.0", "CC BY-NC 4.0", "free to use"):
        with pytest.raises(ValueError):
            fm.normalize_license(raw)
    assert fm.normalize_license("CC0 1.0") == "CC0" and fm.normalize_license("Public domain") == "PD"

    called = []
    res = fm.build(tracks=[cc_by], music=tmp_path, download=lambda u, d: called.append(u))
    assert res["status"] == "error" and res["registered"] == []
    assert "license" in res["rejected"][0]["reason"] and called == []
    assert json.loads((tmp_path / "catalog.json").read_text())["tracks"] == []


def test_fetch_music_verifies_sha256(fm, tmp_path):
    good = dict(reversed_track(fm), sha256="0" * 64)

    def fake_download(url, dest):
        Path(dest).write_bytes(b"not the expected bytes")

    res = fm.build(tracks=[good], music=tmp_path, download=fake_download)
    assert res["rejected"] and "sha256" in res["rejected"][0]["reason"]
    assert not (tmp_path / "nope.ogg").exists() and not (tmp_path / "nope.ogg.part").exists()


def reversed_track(fm):
    t = dict(fm.TRACKS[0])
    t["id"], t["file"] = "nope", "nope.ogg"
    return t


def test_unknown_music_id_is_a_lint_error_and_known_one_is_clean():
    assert "unknown_music" in codes(mk(music={"id": "nope"}))
    assert codes(mk(music={"id": "moonlight-sonata"})) == set()
    assert codes(mk(music={"id": "moonlight-sonata", "volume_db": 3, "duck": -1})) == {
        "bad_music_volume", "bad_music_duck"}
    assert "bad_music" in codes(mk(music={"volume_db": -18}))


def test_music_levels_get_defaults(monkeypatch):
    s = mk(music={"id": "moonlight-sonata"})
    assert s["music"] == {"id": "moonlight-sonata", "volume_db": -18.0, "duck": 12.0}
