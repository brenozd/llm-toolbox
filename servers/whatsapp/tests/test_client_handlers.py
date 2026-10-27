import tempfile

from neonize.proto.Neonize_pb2 import HistorySync as HistorySyncEv
from neonize.proto.Neonize_pb2 import Message as MessageEv
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message as E2E
from whatsapp_mcp import client as wa_client
from whatsapp_mcp.store import Store

PN = "5511999990000"
OWN = "5511900000000@s.whatsapp.net"
TS = 1_700_000_000_000  # whatsmeow sends unix milliseconds


def jid(proto_jid, user, server="s.whatsapp.net"):
    proto_jid.User = user
    proto_jid.Server = server


def message_ev(user, text=None, *, server="s.whatsapp.net", mid="MSG1", from_me=False, group=False,
               pushname="", sender=None):
    ev = MessageEv()
    jid(ev.Info.MessageSource.Chat, user, server)
    if sender or not from_me:
        jid(ev.Info.MessageSource.Sender, sender or user, server)
    ev.Info.MessageSource.IsFromMe = from_me
    ev.Info.MessageSource.IsGroup = group
    ev.Info.ID = mid
    ev.Info.Timestamp = TS
    ev.Info.Pushname = pushname
    if text is not None:
        ev.Message.conversation = text
    return ev


def test_text_message():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        wa_client.on_message(store, message_ev(PN, "hello", pushname="Ann"))
        with store.reader() as r:
            rows = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)
            assert len(rows) == 1, rows
            row = rows[0]
            assert row["content"] == "hello" and row["sender"] == f"{PN}@s.whatsapp.net"
            assert row["timestamp"] == "2023-11-14T22:13:20Z" and row["is_from_me"] is False
            chat = r.get_chat(f"{PN}@s.whatsapp.net")
            assert chat["name"] == "Ann"
        store.close()


def test_own_and_group_messages():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        wa_client.on_message(store, message_ev(PN, "mine", from_me=True, pushname="Me", mid="OWN1"), own_jid=OWN)
        group = message_ev("120363000000000000", "in group", server="g.us", group=True, pushname="Bob", mid="G1")
        wa_client.on_message(store, group)
        with store.reader() as r:
            own = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)[0]
            assert own["is_from_me"] is True and own["sender"] == OWN, own
            grp = r.list_messages(None, None, None, "120363000000000000@g.us", None, 10, 0)[0]
            assert grp["content"] == "in group"
            assert r.get_chat("120363000000000000@g.us")["is_group"] is True
            assert r.get_chat("120363000000000000@g.us")["name"] is None  # group pushnames are not chat names
        store.close()


def test_media_message_and_raw_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = message_ev(PN, None, mid="IMG1")
        ev.Message.imageMessage.caption = "look at this"
        ev.Message.imageMessage.mimetype = "image/jpeg"
        ev.Message.imageMessage.fileLength = 1234
        wa_client.on_message(store, ev)
        with store.reader() as r:
            row = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)[0]
        assert row["content"] == "look at this" and row["media_type"] == "image"
        assert row["filename"] == "image.jpg"
        with store.reader() as r:
            ref = r.get_media_ref("IMG1", f"{PN}@s.whatsapp.net")
        assert ref["file_length"] == 1234, ref
        parsed = E2E.FromString(ref["raw"])
        assert parsed.HasField("imageMessage") and parsed.imageMessage.mimetype == "image/jpeg"
        store.close()


def test_extended_text_and_ignored_messages():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = message_ev(PN, None, mid="EXT1")
        ev.Message.extendedTextMessage.text = "via extended text"
        wa_client.on_message(store, ev)
        wa_client.on_message(store, message_ev(PN, None, mid="EMPTY1"))  # nothing we store
        wa_client.on_message(store, message_ev(PN, "no id", mid=""))  # sender-chosen empty id
        with store.reader() as r:
            rows = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)
        assert [r["content"] for r in rows] == ["via extended text"], rows
        store.close()


def test_agent_device_suffix_is_stripped():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = message_ev(PN, "hi", sender=f"{PN}.0:12")
        wa_client.on_message(store, ev)
        with store.reader() as r:
            row = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)[0]
        assert row["sender"] == f"{PN}@s.whatsapp.net", row
        store.close()


def history_ev(chat_id, name, messages):
    ev = HistorySyncEv()
    conv = ev.Data.conversations.add()
    conv.ID = chat_id
    conv.name = name
    for (mid, text, from_me, participant, ts) in messages:
        wm = conv.messages.add().message
        wm.key.remoteJID = chat_id
        wm.key.ID = mid
        wm.key.fromMe = from_me
        if participant:
            wm.key.participant = participant
        wm.messageTimestamp = ts
        wm.message.conversation = text
    return ev


def test_history_sync():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = history_ev(f"{PN}@s.whatsapp.net", "Ann", [("H1", "old one", False, None, TS), ("H2", "my reply", True, None, TS + 1000)])
        group = ev.Data.conversations.add()
        group.ID = "120363000000000000@g.us"
        wm = group.messages.add().message
        wm.key.remoteJID = "120363000000000000@g.us"
        wm.key.ID = "H3"
        wm.key.participant = f"{PN}@s.whatsapp.net"
        wm.message.conversation = "group history"
        wa_client.on_history(store, ev, own_jid=OWN)
        with store.reader() as r:
            direct = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)
            assert [m["content"] for m in direct] == ["my reply", "old one"], direct
            assert direct[0]["is_from_me"] is True and direct[0]["sender"] == OWN, direct[0]
            assert r.get_chat(f"{PN}@s.whatsapp.net")["name"] == "Ann"
            grp = r.list_messages(None, None, None, "120363000000000000@g.us", None, 10, 0)
            assert grp[0]["sender"] == f"{PN}@s.whatsapp.net", grp
        store.close()


def test_voice_note_and_sender_controlled_filename():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = message_ev(PN, None, mid="VOICE1")
        ev.Message.audioMessage.mimetype = "audio/ogg; codecs=opus"
        ev.Message.audioMessage.fileLength = 999
        ev.Message.audioMessage.PTT = True
        wa_client.on_message(store, ev)
        doc = message_ev(PN, None, mid="DOC1")
        doc.Message.documentMessage.fileName = "../../secrets.env"
        doc.Message.documentMessage.mimetype = "text/plain"
        doc.Message.documentMessage.fileLength = 5
        wa_client.on_message(store, doc)
        with store.reader() as r:
            voice = r.get_media_ref("VOICE1", f"{PN}@s.whatsapp.net")
            document = r.get_media_ref("DOC1", f"{PN}@s.whatsapp.net")
        assert voice["media_type"] == "audio" and voice["filename"] == "audio.ogg", voice
        # kept as data only: the name is sanitized when the file is written
        assert document["filename"] == "../../secrets.env", document
        store.close()


def test_real_client_constructs_offline():
    """Wiring against the real neonize API, without connecting (no network, no QR)."""
    import stat
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        client = wa_client.NeonizeClient(d, store)
        try:
            assert client.is_connected is False and client.is_logged_in is False
            assert client.own_jid() is None
            session = Path(d) / "whatsapp.db"
            assert session.is_file(), "the session DB must be created up front"
            assert stat.S_IMODE(session.stat().st_mode) == 0o600
            assert stat.S_IMODE(Path(d).stat().st_mode) == 0o700
        finally:
            client.close()
            store.close()


def test_ephemeral_wrapper_is_unwrapped():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        ev = message_ev(PN, mid="EPH1")
        ev.Message.ephemeralMessage.message.conversation = "vanishing"
        wa_client.on_message(store, ev)
        with store.reader() as r:
            rows = r.list_messages(None, None, None, f"{PN}@s.whatsapp.net", None, 10, 0)
        assert [m["content"] for m in rows] == ["vanishing"], rows
        store.close()


if __name__ == "__main__":
    test_text_message()
    test_own_and_group_messages()
    test_media_message_and_raw_roundtrip()
    test_extended_text_and_ignored_messages()
    test_agent_device_suffix_is_stripped()
    test_history_sync()
    test_ephemeral_wrapper_is_unwrapped()
    test_voice_note_and_sender_controlled_filename()
    test_real_client_constructs_offline()
    print("ok")
