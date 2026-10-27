import os
import stat
import tempfile
from pathlib import Path

from _fakes import FakeClient
from whatsapp_mcp import audio, tools
from whatsapp_mcp.config import WhatsAppConfig
from whatsapp_mcp.store import Store

PN = "5511999990000"
CHAT = f"{PN}@s.whatsapp.net"


def make_config(d: Path, **over) -> WhatsAppConfig:
    raw = {"data_dir": str(d / "data"), "media_dir": str(d / "media"), "allow_send": True,
           "allowed_recipients": [PN], "max_media_bytes": 1024}
    raw |= over
    cfg = WhatsAppConfig.from_dict(raw)
    Path(cfg.media_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def expect(fn, needle=""):
    try:
        fn()
    except (ValueError, LookupError, RuntimeError) as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError("expected an error")


def test_check_recipient_and_allowlist(d):
    cfg = make_config(d)
    assert tools.check_recipient(cfg, PN) == CHAT
    assert tools.check_recipient(cfg, CHAT) == CHAT  # digits form == JID form
    assert tools.check_recipient(cfg, PN + ".0:3@s.whatsapp.net") == CHAT
    expect(lambda: tools.check_recipient(cfg, "5511888880000"), "allowed_recipients")
    expect(lambda: tools.check_recipient(cfg, "nope"), "phone number")
    open_cfg = make_config(d, allowed_recipients=[])
    assert tools.check_recipient(open_cfg, "5511888880000") == "5511888880000@s.whatsapp.net"


def test_resolve_media_containment(d):
    cfg = make_config(d)
    media_dir = Path(cfg.media_dir)
    (media_dir / "sub").mkdir()
    (media_dir / "sub" / "ok.png").write_bytes(b"png")
    outside = d / "secret.png"
    outside.write_bytes(b"secret")
    (media_dir / "escape.png").symlink_to(outside)
    assert tools.resolve_media(cfg, "sub/ok.png").name == "ok.png"
    expect(lambda: tools.resolve_media(cfg, str(outside)), "relative")
    expect(lambda: tools.resolve_media(cfg, "../secret.png"), "'..'")
    expect(lambda: tools.resolve_media(cfg, "escape.png"), "inside the media dir")
    expect(lambda: tools.resolve_media(cfg, "missing.png"), "not found")
    big = media_dir / "big.bin"
    big.write_bytes(b"x" * 2048)
    expect(lambda: tools.resolve_media(cfg, "big.bin"), "max_media_bytes")
    expect(lambda: tools.resolve_media(cfg, ""), "relative")


def test_download_media(d):
    cfg = make_config(d, max_media_bytes=64)
    store = Store(cfg.data_dir)
    client = FakeClient(media=b"payload")
    store.add_message(id="IMG1", chat_jid=CHAT, sender=CHAT, content="", timestamp="2024-01-01T10:00:00Z",
                      media_type="image", filename="cat.jpg", file_length=7, raw=b"raw-proto")
    out = tools.download_media(cfg, store, client, "IMG1", CHAT)
    assert client.downloaded == [b"raw-proto"], client.downloaded
    path = Path(out["path"])
    assert path.read_bytes() == b"payload" and path.name == "IMG1-cat.jpg"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert out["content_is_untrusted"] is True and out["media_type"] == "image"
    again = tools.download_media(cfg, store, client, "IMG1", CHAT)
    assert again["path"] != out["path"], "downloads must never overwrite"
    store.add_message(id="DOC2", chat_jid=CHAT, sender=CHAT, content="", timestamp="2024-01-02T10:00:00Z",
                      media_type="document", filename="../../../evil.sh", file_length=7, raw=b"raw-proto")
    hostile = Path(tools.download_media(cfg, store, client, "DOC2", CHAT)["path"])
    assert hostile.parent.name == "downloads", hostile
    assert hostile.name.startswith("DOC2-") and "/" not in hostile.name, hostile
    expect(lambda: tools.download_media(cfg, store, client, "nope", CHAT), "no downloadable media")
    store.close()


def test_download_media_size_cap_is_pre_download(d):
    cfg = make_config(d, max_media_bytes=8)
    store = Store(cfg.data_dir)
    client = FakeClient()
    store.add_message(id="BIG", chat_jid=CHAT, sender=CHAT, content="", timestamp="2024-01-01T10:00:00Z",
                      media_type="video", filename="big.mp4", file_length=9_000_000, raw=b"raw")
    expect(lambda: tools.download_media(cfg, store, client, "BIG", CHAT), "max_media_bytes")
    assert client.downloaded == [], "must check file_length before downloading"
    store.close()


def test_download_media_refuses_unknown_length(d):
    cfg = make_config(d)
    store = Store(cfg.data_dir)
    client = FakeClient()
    store.add_message(id="Z", chat_jid=CHAT, sender=CHAT, content="", timestamp="2024-01-01T10:00:00Z",
                      media_type="video", filename="z.mp4", file_length=0, raw=b"raw")
    expect(lambda: tools.download_media(cfg, store, client, "Z", CHAT), "max_media_bytes")
    assert client.downloaded == []
    store.close()


def test_send_message_stores_outgoing(d):
    cfg = make_config(d)
    store = Store(cfg.data_dir)
    client = FakeClient()
    res = tools.send_message(cfg, store, client, PN, "hello there")
    assert client.sent == [("text", CHAT, "hello there")], client.sent
    assert res["success"] is True and res["message_id"] == "sent-1"
    with store.reader() as r:
        rows = r.list_messages(None, None, None, CHAT, None, 10, 0)
        assert len(rows) == 1 and rows[0]["is_from_me"] is True, rows
        assert rows[0]["content"] == "hello there" and rows[0]["sender"] == PN + "@s.whatsapp.net"
    expect(lambda: tools.send_message(cfg, store, client, PN, "   "), "must not be empty")
    expect(lambda: tools.send_message(cfg, store, client, "5511888880000", "hi"), "allowed_recipients")
    store.close()


def test_send_file_kinds(d):
    cfg = make_config(d)
    store = Store(cfg.data_dir)
    client = FakeClient()
    media_dir = Path(cfg.media_dir)
    (media_dir / "a.png").write_bytes(b"png")
    (media_dir / "b.pdf").write_bytes(b"pdf")
    (media_dir / "c.mp4").write_bytes(b"mp4")
    assert tools.send_file(cfg, store, client, PN, "a.png")["media_type"] == "image"
    assert tools.send_file(cfg, store, client, PN, "b.pdf")["media_type"] == "document"
    assert tools.send_file(cfg, store, client, PN, "c.mp4")["media_type"] == "video"
    assert [s[0] for s in client.sent] == ["image", "document", "video"]
    assert client.sent[0][2] == b"png" and client.sent[0][3] == "a.png"
    with store.reader() as r:
        rows = {row["filename"]: row for row in r.list_messages(None, None, None, CHAT, None, 10, 0)}
        assert rows["b.pdf"]["media_type"] == "document" and rows["b.pdf"]["is_from_me"] is True, rows
        assert rows["c.mp4"]["media_type"] == "video" and rows["a.png"]["media_type"] == "image", rows
    expect(lambda: tools.send_file(cfg, store, client, PN, "../b.pdf"), "'..'")
    store.close()


def test_send_audio_message_transcodes_in_tempdir(d):
    cfg = make_config(d)
    store = Store(cfg.data_dir)
    client = FakeClient()
    src = Path(cfg.media_dir) / "note.wav"
    src.write_bytes(b"wav")
    seen = []
    original = audio.convert_to_opus_ogg

    def fake_convert(source, dest):
        seen.append(Path(dest))
        Path(dest).write_bytes(b"ogg-bytes")

    audio.convert_to_opus_ogg = fake_convert
    try:
        res = tools.send_audio_message(cfg, store, client, PN, "note.wav")
    finally:
        audio.convert_to_opus_ogg = original
    assert res["media_type"] == "audio"
    assert client.sent == [("voice", CHAT, b"ogg-bytes", "voice.ogg")], client.sent
    assert seen and seen[0].name == "voice.ogg"
    assert not seen[0].parent.exists(), "the tempdir must be removed"
    assert not (Path(cfg.media_dir) / "voice.ogg").exists()
    store.close()


def test_audio_ffmpeg_missing_is_reported(d):
    src = d / "a.wav"
    src.write_bytes(b"wav")
    dst = d / "a.ogg"
    real_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(d)  # no ffmpeg anywhere
    try:
        expect(lambda: audio.convert_to_opus_ogg(src, dst), "ffmpeg")
    finally:
        os.environ["PATH"] = real_path


def test_send_is_refused_when_disabled(d):
    cfg = make_config(d, allow_send=False)
    store = Store(cfg.data_dir)
    client = FakeClient()
    expect(lambda: tools.send_message(cfg, store, client, PN, "hi"), "allow_send")
    expect(lambda: tools.send_file(cfg, store, client, PN, "x.png"), "allow_send")
    assert client.sent == []
    store.close()


def test_check_connection(d):
    cfg = make_config(d)
    assert tools.check_connection(cfg, FakeClient()) == {"connected": True, "logged_in": True, "allow_send": True}
    assert tools.check_connection(cfg, FakeClient(connected=False))["connected"] is False


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for fn in (test_check_recipient_and_allowlist, test_resolve_media_containment, test_download_media,
                   test_download_media_size_cap_is_pre_download, test_download_media_refuses_unknown_length,
                   test_send_message_stores_outgoing,
                   test_send_file_kinds, test_send_audio_message_transcodes_in_tempdir,
                   test_audio_ffmpeg_missing_is_reported, test_send_is_refused_when_disabled,
                   test_check_connection):
            sub = Path(tmp) / fn.__name__
            sub.mkdir()
            fn(sub)


if __name__ == "__main__":
    main()
    print("ok")
