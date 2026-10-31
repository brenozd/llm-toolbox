"""Delivery bookkeeping: the name is the contract, CURRENT must never be stale, and a round is one file."""
import os
from pathlib import Path

import pytest

from storyboard_video_mcp import config, delivery as D


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK", tmp_path)
    return tmp_path


def render(work, name="delivery.mp4", data=b"\0" * 4096):
    p = work / "out" / "abc123" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_the_name_is_the_contract():
    assert D.delivery_name("mint", "16:9", 3, "2026-03-01") == "mint_v03_16x9_2026-03-01.mp4"
    assert D.delivery_name("mint", "9:16", "v7", "2026-03-01") == "mint_v07_9x16_2026-03-01.mp4"
    assert D.delivery_name("my_proj.v2", "16x9", 1, "2026-12-31") == "my_proj.v2_v01_16x9_2026-12-31.mp4"


@pytest.mark.parametrize("project", ["../evil", "a/b", "a\\b", "a b", "..", ".hidden", "-n", "x" * 65, ""])
def test_names_with_separators_or_odd_chars_are_refused(work, project):
    with pytest.raises(ValueError):
        D.deliver(project, "16:9", 1, "2026-03-01", render(work))
    assert not (work / "deliveries").exists()  # refused before a single byte is written


@pytest.mark.parametrize("aspect,version,date", [("4:3", 1, "2026-03-01"), ("16:9", 0, "2026-03-01"),
                                                 ("16:9", True, "2026-03-01"), ("16:9", "v", "2026-03-01"),
                                                 ("16:9", 1, "2026-02-30"), ("16:9", 1, "01/02/2026")])
def test_bad_aspect_version_or_date_is_refused(work, aspect, version, date):
    with pytest.raises(ValueError):
        D.deliver("mint", aspect, version, date, render(work))


def test_deliver_copies_the_render_and_points_current(work):
    src = render(work, data=b"MP4PAYLOAD")
    rec = D.deliver("mint", "16:9", 1, "2026-03-01", src)
    dest = work / "deliveries" / "mint_v01_16x9_2026-03-01.mp4"
    assert rec["video"] == str(dest) and dest.read_bytes() == b"MP4PAYLOAD"
    assert src.exists()  # copy, never move: the render dir keeps its file
    assert D.current() == dest.resolve() and os.readlink(work / "deliveries" / "CURRENT") == dest.name
    assert not (work / "deliveries" / (".CURRENT.tmp")).exists()
    assert not list((work / "deliveries").glob("*.part"))  # the copy landed as a rename, not a half file


def test_a_new_delivery_archives_the_old_one_and_moves_current(work):
    a = D.deliver("mint", "16:9", 1, "2026-03-01", render(work))
    other = D.deliver("mint", "9:16", 1, "2026-03-01", render(work, "v.mp4"))
    stray = work / "deliveries" / "mint_v01_16x9_2026-03-01.mp4.bak"
    stray.write_bytes(b"note")  # not a delivery: the pattern must not swallow it
    b = D.deliver("mint", "16:9", 2, "2026-03-01", render(work))
    old = work / "deliveries" / "mint_v01_16x9_2026-03-01.mp4"
    assert not old.exists() and (work / "deliveries" / "archive" / old.name).is_file()
    assert b["archived"] == [str(work / "deliveries" / "archive" / old.name)]
    assert D.current().name == "mint_v02_16x9_2026-03-01.mp4"
    assert (work / "deliveries" / "mint_v01_9x16_2026-03-01.mp4").is_file()  # the other aspect is another video
    assert other["archived"] == [] and stray.is_file()


def test_a_stale_current_is_replaced(work):
    d = work / "deliveries"
    d.mkdir(parents=True)
    (d / "CURRENT").write_text("mint_v09_16x9_2020-01-01.mp4\n")  # a text pointer to a file that is gone
    rec = D.deliver("mint", "16:9", 1, "2026-03-01", render(work))
    assert D.current().name == "mint_v01_16x9_2026-03-01.mp4"
    (d / "CURRENT").unlink()
    os.symlink("gone.mp4", d / "CURRENT")  # a dangling link is a stale pointer too
    assert D.current() is not None and not D.current().exists()
    D.deliver("mint", "16:9", 2, "2026-03-01", render(work))
    assert D.current() == (d / "mint_v02_16x9_2026-03-01.mp4").resolve()
    assert rec["name"] == "mint_v01_16x9_2026-03-01.mp4"  # the first delivery kept its own name
    assert not list(d.glob(".CURRENT.tmp"))


def test_deliver_refuses_a_missing_render_and_a_secret_path(work):
    with pytest.raises(FileNotFoundError):
        D.deliver("mint", "16:9", 1, "2026-03-01", work / "out" / "nope.mp4")
    with pytest.raises(PermissionError):
        D.deliver("mint", "16:9", 1, "2026-03-01", "/etc/passwd")


def test_an_existing_delivery_is_never_overwritten(work):
    """A published name is never reused: a newer cut is a version bump, not a silent edit of the file a
    reviewer already signed off."""
    D.deliver("mint", "16:9", 1, "2026-03-01", render(work, data=b"FIRST"))
    with pytest.raises(D.DeliveryError) as e:
        D.deliver("mint", "16:9", 1, "2026-03-01", render(work, data=b"SECOND"))
    assert e.value.code == "delivery_exists" and "bump version" in e.value.fix
    assert isinstance(e.value, ValueError)  # callers that already catch ValueError keep working
    dest = work / "deliveries" / "mint_v01_16x9_2026-03-01.mp4"
    assert dest.read_bytes() == b"FIRST" and D.current() == dest.resolve()  # the delivery is untouched
    assert not list(dest.parent.glob("*.part"))


def test_the_srt_and_credits_ship_beside_the_delivered_mp4(work):
    """The published folder is what a client opens: subtitles and the credit block travel with the video."""
    src = render(work, data=b"MP4PAYLOAD")
    (src.parent / "delivery.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n\n")
    (src.parent / "CREDITS.txt").write_text("Music credits\n- Slow by Someone, CC0 1.0\n")
    rec = D.deliver("mint", "16:9", 1, "2026-03-01", src)
    d = work / "deliveries"
    srt = d / "mint_v01_16x9_2026-03-01.srt"
    assert srt.read_text().endswith("Hi\n\n")  # same basename as the mp4 it subtitles
    assert (d / "CREDITS.txt").read_text().startswith("Music credits")
    assert rec["srt"] == str(srt) and rec["credits"] == str(d / "CREDITS.txt")
    assert (src.parent / "delivery.srt").is_file()  # copy, never move


def test_a_render_with_no_srt_or_credits_reports_none(work):
    rec = D.deliver("mint", "16:9", 1, "2026-03-01", render(work))
    assert rec["srt"] is None and rec["credits"] is None
    assert [p.name for p in (work / "deliveries").iterdir() if p.name != D.CURRENT] == [rec["name"]]


def test_a_failed_copy_leaves_no_part_file(work, monkeypatch):
    """A killed copy used to leave delivery.mp4.part lying in the published folder."""
    def boom(src, dst):
        Path(dst).write_bytes(b"half a video")
        raise OSError("no space left on device")

    monkeypatch.setattr(D.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        D.deliver("mint", "16:9", 1, "2026-03-01", render(work))
    d = work / "deliveries"
    assert not list(d.glob("*.part")) and not (d / "mint_v01_16x9_2026-03-01.mp4").exists()


def test_round_log_writes_exactly_one_file(work):
    p = D.round_log(work, 3, "Is the hook under 3 s?",
                    notes=[{"timecode": "00:02", "severity": "must", "text": "cut the intro"},
                           {"timecode": 4.5, "severity": "PREF", "text": "brighter card"}],
                    decision="cut to 2.1 s", hash_before="aaaa", hash_after="bbbb")
    assert [f.name for f in (work / "rounds").iterdir()] == ["3.md"] and p == str(work / "rounds" / "3.md")
    txt = (work / "rounds" / "3.md").read_text()
    assert txt.startswith("# Round 3")
    for want in ("Is the hook under 3 s?", "- `00:02` **must** cut the intro", "- `4.5s` **pref** brighter card",
                 "**Decision:** cut to 2.1 s", "`spec_hash` before: `aaaa`", "`spec_hash` after: `bbbb`"):
        assert want in txt
    D.round_log(work, 3, "Is the hook under 3 s?", decision="actually keep 2.4 s")
    assert [f.name for f in (work / "rounds").iterdir()] == ["3.md"]
    assert "actually keep 2.4 s" in (work / "rounds" / "3.md").read_text()


def test_round_log_is_bounded_and_validated(work):
    notes = [{"timecode": "00:%02d" % i, "severity": "must", "text": "t " * 400} for i in range(100)]
    txt = Path(D.round_log(work, 1, "q " * 3000, notes=notes)).read_text()
    assert len(txt) < 13000 and txt.count("**must**") == D.NOTES_MAX and "…" in txt  # capped, not dropped silently
    assert "**Notes:**\n- (none)" in Path(D.round_log(work, 2, "empty round")).read_text()
    for bad in [{"n": 0}, {"n": "1"}, {"n": True}]:
        with pytest.raises(ValueError):
            D.round_log(work, bad["n"], "q")
    with pytest.raises(ValueError):  # a severity nobody can act on is not a note
        D.round_log(work, 4, "q", notes=[{"timecode": "00:01", "severity": "info", "text": "meh"}])
    with pytest.raises(ValueError):
        D.round_log(work, 5, "q", notes=["00:01 must cut"])


def cow(**kw):
    return {"scenes": [{"id": "a", "type": "title", "title": "Hi"}], **kw}


def test_delivery_check_finds_the_missing_pieces(work):
    vid = work / "out" / "abc123"
    vid.mkdir(parents=True)
    codes = {f["code"] for f in D.delivery_check(cow(music={"path": "/music/x.mp3", "license": "CC0 1.0"}), vid)}
    assert codes == {"srt_missing", "credits_missing"}
    (vid / "delivery.srt").write_text("")
    assert "srt_missing" in {f["code"] for f in D.delivery_check(cow(), vid)}  # an empty file is no subtitle
    (vid / "delivery.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n\n")
    (vid / "CREDITS.txt").write_text("Music credits\n- Slow by Someone, CC0 1.0\n")
    assert D.delivery_check(cow(music={"path": "/music/x.mp3", "license": "CC0 1.0"}), vid) == []


def test_delivery_check_reads_the_music_licence(work):
    vid = work / "out" / "abc123"
    vid.mkdir(parents=True)
    (vid / "delivery.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n\n")
    (work / "CREDITS.txt").write_text("Music credits\n")  # the /work copy counts when the video one is gone

    def codes(spec):
        return {f["code"] for f in D.delivery_check(spec, vid)}

    assert codes(cow(music={"path": "/music/x.mp3", "license": "CC BY-SA 4.0"})) == {"music_license_incompatible"}
    assert codes(cow(music={"path": "/music/x.mp3", "license": "CC BY 4.0"})) == {"music_license_missing"}
    assert codes(cow(music={"path": "/music/x.mp3"})) == {"music_license_missing"}
    by = {"path": "/music/x.mp3", "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
          "attribution": "Slow by Someone, CC BY 4.0"}
    assert codes(cow(music=by)) == set()


def test_delivery_check_gates_library_effects_on_cc0(work):
    vid = work / "out" / "abc123"
    vid.mkdir(parents=True)
    (vid / "delivery.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n\n")
    spec = cow(scenes=[{"id": "a", "type": "title", "title": "Hi",
                        "sfx": [{"at": 0, "path": "/sfx/whoosh-1.wav", "license": "CC BY 4.0"}]}])
    assert [f["code"] for f in D.delivery_check(spec, vid)] == ["credits_missing", "sfx_license_incompatible"]
    (vid / "CREDITS.txt").write_text("Sound effect credits\n- whoosh · CC0\n")
    spec["scenes"][0]["sfx"][0]["license"] = "CC0 1.0"
    assert D.delivery_check(spec, vid) == []  # procedural sfx need nothing; a CC0 library clip is credited
    assert D.delivery_check(cow(scenes=[{"id": "a", "type": "title", "title": "Hi",
                                         "sfx": [{"at": 0, "kind": "tick"}]}]), vid) == []
