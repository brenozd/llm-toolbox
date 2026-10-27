import sqlite3
import tempfile
from pathlib import Path

from whatsapp_mcp.store import MAX_CONTENT, Store, iso_utc

PN = "5511999990000"
LID = "123456789012345"


def session_db(data_dir: Path, lids=(), contacts=()):
    """Mimic the whatsmeow session schema (verified against the Go core's CREATE TABLE statements)."""
    db = sqlite3.connect(data_dir / "whatsapp.db")
    db.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT PRIMARY KEY, pn TEXT UNIQUE NOT NULL)")
    db.execute("CREATE TABLE whatsmeow_contacts (our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT,"
               " push_name TEXT, business_name TEXT, redacted_phone TEXT, PRIMARY KEY (our_jid, their_jid))")
    db.executemany("INSERT INTO whatsmeow_lid_map (lid, pn) VALUES (?, ?)", lids)
    db.executemany("INSERT INTO whatsmeow_contacts (our_jid, their_jid, first_name, full_name, push_name)"
                   " VALUES ('me', ?, ?, ?, ?)", contacts)
    db.commit()
    db.close()


def with_store(fn):
    def run():
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            try:
                fn(store, Path(d))
            finally:
                store.close()
    return run


@with_store
def test_add_and_list(store, d):
    store.add_message(id="m1", chat_jid=f"{PN}@s.whatsapp.net", sender=f"{PN}@s.whatsapp.net", content="hello",
                      timestamp="2024-01-01T10:00:00Z", chat_name="Ann")
    store.add_message(id="m2", chat_jid=f"{PN}@s.whatsapp.net", sender="me", content="x" * (MAX_CONTENT + 10),
                      timestamp="2024-01-01T11:00:00Z", is_from_me=True)
    with store.reader() as r:
        msgs = r.list_messages(limit=10, offset=0, after=None, before=None, sender_phone_number=None,
                               chat_jid=f"{PN}@s.whatsapp.net", query=None)
        assert [m["id"] for m in msgs] == ["m2", "m1"], msgs
        assert msgs[1]["content"] == "hello" and msgs[1]["is_from_me"] is False
        assert msgs[0]["truncated"] is True and len(msgs[0]["content"]) == MAX_CONTENT
        chat = r.get_chat(f"{PN}@s.whatsapp.net")
        assert chat["name"] == "Ann" and chat["last_message_time"] == "2024-01-01T11:00:00Z"
        assert chat["last_message"].startswith("x") and chat["last_is_from_me"] is True


@with_store
def test_duplicate_id_does_not_overwrite(store, d):
    chat = f"{PN}@s.whatsapp.net"
    store.add_message(id="dup", chat_jid=chat, sender=chat, content="first", timestamp="2024-01-01T10:00:00Z")
    store.add_message(id="dup", chat_jid=chat, sender=chat, content="second", timestamp="2024-01-02T10:00:00Z")
    with store.reader() as r:
        rows = r.list_messages(None, None, None, chat, None, 10, 0)
        assert len(rows) == 1 and rows[0]["content"] == "first", rows


@with_store
def test_last_message_time_is_max(store, d):
    chat = f"{PN}@s.whatsapp.net"
    store.add_message(id="1", chat_jid=chat, sender=chat, content="a", timestamp="2024-05-01T10:00:00Z")
    store.add_message(id="2", chat_jid=chat, sender=chat, content="b", timestamp="2024-01-01T10:00:00Z")
    with store.reader() as r:
        assert r.get_chat(chat)["last_message_time"] == "2024-05-01T10:00:00Z"
        # equal timestamps must not duplicate the chat in list_chats
        store.add_message(id="3", chat_jid=chat, sender=chat, content="c", timestamp="2024-05-01T10:00:00Z")
        rows = r.list_chats(None, 50, 0, True, "last_active")
        assert len([c for c in rows if c["jid"] == chat]) == 1, rows


@with_store
def test_contact_chats_deduped(store, d):
    other = "5511888880000@s.whatsapp.net"
    group = "120363000000000000@g.us"
    for i in range(5):
        store.add_message(id=f"g{i}", chat_jid=group, sender=f"{PN}@s.whatsapp.net", content=f"m{i}",
                          timestamp=f"2024-01-0{i + 1}T10:00:00Z")
    store.add_message(id="d1", chat_jid=other, sender=f"{PN}@s.whatsapp.net", content="dm",
                      timestamp="2024-02-01T10:00:00Z")
    with store.reader() as r:
        chats = r.get_contact_chats(f"{PN}@s.whatsapp.net", 50, 0)
        assert len(chats) == 2, chats
        assert chats[0]["jid"] == other and chats[0]["last_message"] == "dm"


@with_store
def test_paging_and_validation(store, d):
    chat = f"{PN}@s.whatsapp.net"
    for i in range(5):
        store.add_message(id=f"p{i}", chat_jid=chat, sender=chat, content=str(i),
                          timestamp=f"2024-01-0{i + 1}T10:00:00Z")
    with store.reader() as r:
        assert len(r.list_messages(None, None, None, chat, None, 2, 2)) == 2
        for kwargs in ({"limit": 0}, {"limit": 201}, {"limit": 10, "offset": -1}):
            try:
                r.list_messages(None, None, None, chat, None, kwargs.get("limit", 10), kwargs.get("offset", 0))
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError for {kwargs}")
        try:
            r.list_chats(None, 10, 0, True, "nope")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for sort_by")


@with_store
def test_query_is_escaped_and_parameterized(store, d):
    chat = f"{PN}@s.whatsapp.net"
    store.add_message(id="q1", chat_jid=chat, sender=chat, content="100% sure", timestamp="2024-01-01T10:00:00Z")
    store.add_message(id="q2", chat_jid=chat, sender=chat, content="100 pct", timestamp="2024-01-02T10:00:00Z")
    with store.reader() as r:
        assert [m["id"] for m in r.list_messages(None, None, None, chat, "100%", 10, 0)] == ["q1"]
        assert [m["id"] for m in r.list_messages(None, None, None, chat, "100", 10, 0)] == ["q2", "q1"]
        assert r.get_chat("x'; DROP TABLE messages; --") is None
        assert len(r.list_messages(None, None, None, chat, None, 10, 0)) == 2


def test_lid_aware_names_and_phones():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        session_db(Path(d), lids=[(LID, PN)], contacts=[(f"{LID}@lid", "Ann", "Ann Lee", "ann")])
        store.add_message(id="l1", chat_jid=f"{LID}@lid", sender=f"{LID}@lid", content="hi",
                          timestamp="2024-01-01T10:00:00Z")
        store.add_message(id="u1", chat_jid="999999999999999@lid", sender="999999999999999@lid", content="yo",
                          timestamp="2024-01-02T10:00:00Z")
        with store.reader() as r:
            mapped = r.get_chat(f"{LID}@lid")
            assert mapped["phone_number"] == PN and mapped["name"] == "Ann Lee", mapped
            unmapped = r.get_chat("999999999999999@lid")
            assert "phone_number" not in unmapped, unmapped
            # phone search finds the LID-keyed chat through the lid map
            found = r.get_direct_chat_by_contact(PN)
            assert found and found["jid"] == f"{LID}@lid", found
            assert r.get_direct_chat_by_contact("5511000000000") is None
            # variants bridge the two namespaces
            assert f"{LID}@lid" in r.variants(f"{PN}@s.whatsapp.net")
            assert f"{PN}@s.whatsapp.net" in r.variants(f"{LID}@lid")
        store.close()


def test_get_message_context_and_media_ref():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        chat = f"{PN}@s.whatsapp.net"
        for i in range(3):
            store.add_message(id=f"c{i}", chat_jid=chat, sender=chat, content=f"m{i}",
                              timestamp=f"2024-01-0{i + 1}T10:00:00Z")
        store.add_message(id="img", chat_jid=chat, sender=chat, content="", timestamp="2024-01-04T10:00:00Z",
                          media_type="image", filename="cat.jpg", file_length=42, raw=b"\x01\x02")
        with store.reader() as r:
            ctx = r.get_message_context("c1", 1, 1)
            assert ctx["message"]["id"] == "c1"
            assert [m["id"] for m in ctx["before"]] == ["c0"] and [m["id"] for m in ctx["after"]] == ["c2"]
            try:
                r.get_message_context("nope", 1, 1)
            except LookupError:
                pass
            else:
                raise AssertionError("expected LookupError")
            ref = r.get_media_ref("img", chat)
            assert ref["media_type"] == "image" and ref["raw"] == b"\x01\x02" and ref["file_length"] == 42
            assert r.get_media_ref("img", "other@lid") is None
            assert r.get_media_ref("c1", chat) is None
        store.close()


def test_iso_timestamp_helper():
    assert iso_utc(0) == "1970-01-01T00:00:00Z"
    assert iso_utc(1700000000) == "2023-11-14T22:13:20Z"


if __name__ == "__main__":
    test_add_and_list()
    test_duplicate_id_does_not_overwrite()
    test_last_message_time_is_max()
    test_contact_chats_deduped()
    test_paging_and_validation()
    test_query_is_escaped_and_parameterized()
    test_lid_aware_names_and_phones()
    test_get_message_context_and_media_ref()
    test_iso_timestamp_helper()
    print("ok")
