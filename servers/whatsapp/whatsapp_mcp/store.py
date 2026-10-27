"""Message store (own sqlite DB written by the event handlers) and read-only queries. All SQL is parameterized."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .jid import DEFAULT_SERVER, digits, is_group, norm, split

MAX_LIMIT = 200
MAX_CONTENT = 4000
DB_NAME = "messages.db"
SESSION_DB = "whatsapp.db"  # neonize/whatsmeow session store (account keys), written by the client only

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TEXT, is_from_me INTEGER,
    media_type TEXT, filename TEXT, file_length INTEGER, raw BLOB,
    PRIMARY KEY (id, chat_jid), FOREIGN KEY (chat_jid) REFERENCES chats(jid));
CREATE INDEX IF NOT EXISTS messages_chat_ts ON messages(chat_jid, timestamp);
"""
_MSG_COLS = "m.id, m.chat_jid, c.name, m.sender, m.content, m.timestamp, m.is_from_me, m.media_type, m.filename"
_CHAT_COLS = "c.jid, c.name, c.last_message_time"
_LAST_COLS = ", l.content, l.sender, l.is_from_me"
# newest message per chat, picked by rowid so equal timestamps cannot duplicate a chat
_LAST_JOIN = ("LEFT JOIN messages l ON l.rowid = (SELECT x.rowid FROM messages x WHERE x.chat_jid = c.jid "
              "ORDER BY x.timestamp DESC, x.rowid DESC LIMIT 1)")


def iso_utc(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_arg(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    return iso_utc((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return limit, offset


def _ctx(n: int) -> int:
    return max(0, min(n, 20))


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Store:
    """Writer side. Thread-safe: neonize calls handlers from Go callback threads."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.data_dir / DB_NAME
        os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        os.chmod(self.path, 0o600)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def upsert_chat(self, jid: str, name: str | None = None, ts: str | None = None) -> None:
        with self._lock, self._db:
            self._chat(jid, name, ts)

    def _chat(self, jid: str, name: str | None, ts: str | None) -> None:
        self._db.execute(
            "INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?) ON CONFLICT(jid) DO UPDATE SET "
            "name = COALESCE(excluded.name, name), "
            "last_message_time = MAX(COALESCE(last_message_time, ''), COALESCE(excluded.last_message_time, ''))",
            (jid, name or None, ts))

    def add_message(self, *, id: str, chat_jid: str, sender: str, content: str = "", timestamp: str,
                    is_from_me: bool = False, chat_name: str | None = None, media_type: str | None = None,
                    filename: str | None = None, file_length: int | None = None, raw: bytes | None = None) -> None:
        with self._lock, self._db:
            self._chat(chat_jid, chat_name, timestamp)
            # DO NOTHING: a sender-chosen id must never overwrite an existing row
            self._db.execute(
                "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, "
                "file_length, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id, chat_jid) DO NOTHING",
                (id, chat_jid, sender, content, timestamp, int(is_from_me), media_type, filename, file_length, raw))

    @contextmanager
    def reader(self):
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            yield Reader(conn, self.data_dir / SESSION_DB)
        finally:
            conn.close()


class Reader:
    """Read-only queries on one connection (one per tool call)."""

    def __init__(self, conn: sqlite3.Connection, session_path: Path):
        self.conn = conn
        self.session_path = session_path
        self._ident: tuple[dict[str, str], dict[str, str]] | None = None

    def _all(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.conn.execute(sql, params).fetchall()

    # -- identity (whatsmeow_lid_map: lid -> pn; whatsmeow_contacts: jid -> name)
    def _identity(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._ident is None:
            lids: dict[str, str] = {}
            names: dict[str, str] = {}
            if self.session_path.is_file():
                try:
                    s: sqlite3.Connection | None = sqlite3.connect(
                        f"{self.session_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
                except sqlite3.Error:
                    s = None
                if s:
                    try:
                        # whatsmeow stores bare users here, but accept full JIDs too
                        for lid, pn in s.execute("SELECT lid, pn FROM whatsmeow_lid_map"):
                            lids[norm(lid)] = norm(pn)
                    except sqlite3.Error:
                        pass
                    try:
                        for their_jid, first, full, push, biz in s.execute(
                                "SELECT their_jid, first_name, full_name, push_name, business_name "
                                "FROM whatsmeow_contacts"):
                            if name := full or first or push or biz:
                                names[norm(their_jid)] = name
                    except sqlite3.Error:
                        pass
                    finally:
                        s.close()
            self._ident = (lids, names)
        return self._ident

    def phone_of(self, jid: str) -> str | None:
        """Phone number for a JID; None for an unmapped LID or a group."""
        user, server = split(jid)
        if server == DEFAULT_SERVER:
            return user
        return self._identity()[0].get(user) if server == "lid" else None

    def variants(self, jid: str) -> list[str]:
        """The JID plus its LID/phone counterparts."""
        lids = self._identity()[0]
        user, server = split(jid)
        out = [jid]
        if server == DEFAULT_SERVER:
            out += [f"{lid}@lid" for lid, pn in lids.items() if pn == user]
        elif server == "lid" and user in lids:
            out.append(f"{lids[user]}@{DEFAULT_SERVER}")
        return out

    def _enrich(self, item: dict) -> dict:
        jid = item["jid"]
        phone = self.phone_of(jid)
        if phone:
            item["phone_number"] = phone
        user = split(jid)[0]
        if not item.get("name") or item["name"] == user:
            names = self._identity()[1]
            item["name"] = (names.get(jid) or (names.get(f"{phone}@{DEFAULT_SERVER}") if phone else None)
                            or item.get("name"))
        return item

    # -- row mappers
    @staticmethod
    def _msg(r: tuple) -> dict:
        content = r[4]
        return {
            "id": r[0], "chat_jid": r[1], "chat_name": r[2], "sender": r[3],
            "content": content[:MAX_CONTENT] if content else content,
            "truncated": bool(content and len(content) > MAX_CONTENT),
            "timestamp": r[5], "is_from_me": bool(r[6]), "media_type": r[7] or None, "filename": r[8] or None,
        }

    def _chat_item(self, r: tuple, with_last: bool = True) -> dict:
        chat = {"jid": r[0], "name": r[1], "last_message_time": r[2], "is_group": is_group(r[0])}
        if with_last:
            content = r[3]
            chat |= {"last_message": content[:MAX_CONTENT] if content else content,
                     "last_sender": r[4], "last_is_from_me": None if r[5] is None else bool(r[5])}
        return self._enrich(chat)

    def _chat_sql(self, with_last: bool) -> str:
        return (f"SELECT {_CHAT_COLS}{_LAST_COLS if with_last else ''} FROM chats c "
                f"{_LAST_JOIN if with_last else ''}")

    # -- queries
    def search_contacts(self, query: str) -> list[dict]:
        q = query.lower()
        out = []
        for jid, name in self._all("SELECT jid, name FROM chats WHERE jid NOT LIKE '%@g.us' ORDER BY name, jid"):
            c = self._enrich({"name": name, "jid": jid})
            phone = c.get("phone_number")
            if any(q in (v or "").lower() for v in (c["name"], jid, phone)):
                out.append({"phone_number": phone, "name": c["name"], "jid": jid})
        return out[:50]

    def list_chats(self, query: str | None, limit: int, offset: int, include_last_message: bool, sort_by: str) -> list[dict]:
        limit, offset = _page(limit, offset)
        if sort_by not in ("last_active", "name"):
            raise ValueError("sort_by must be 'last_active' or 'name'")
        sql = self._chat_sql(include_last_message)
        params: list = []
        if query:
            sql += " WHERE (c.name LIKE ? ESCAPE '\\' OR c.jid LIKE ? ESCAPE '\\')"
            params += [_like(query)] * 2
        sql += " ORDER BY c.last_message_time DESC, c.jid" if sort_by == "last_active" else " ORDER BY c.name, c.jid"
        rows = self._all(sql + " LIMIT ? OFFSET ?", (*params, limit, offset))
        return [self._chat_item(r, include_last_message) for r in rows]

    def get_chat(self, chat_jid: str, include_last_message: bool = True) -> dict | None:
        rows = self._all(self._chat_sql(include_last_message) + " WHERE c.jid = ? LIMIT 1", (chat_jid,))
        return self._chat_item(rows[0], include_last_message) if rows else None

    def get_direct_chat_by_contact(self, phone_number: str) -> dict | None:
        d = digits(phone_number)
        # exact phone JID first (plus its known LID aliases), then a LIKE fallback
        exact = self.variants(f"{d}@{DEFAULT_SERVER}")
        base = self._chat_sql(True) + " WHERE c.jid NOT LIKE '%@g.us' AND "
        rows = self._all(base + f"c.jid IN ({','.join('?' * len(exact))}) "
                         "ORDER BY c.last_message_time DESC, c.jid LIMIT 1", tuple(exact))
        if not rows:
            lids = self._identity()[0]
            partial = [f"{lid}@lid" for lid, pn in lids.items() if d in pn][:50]
            clause, params = "c.jid LIKE ? ESCAPE '\\'", [_like(d)]
            if partial:
                clause += f" OR c.jid IN ({','.join('?' * len(partial))})"
                params += partial
            rows = self._all(base + f"({clause}) ORDER BY c.last_message_time DESC, c.jid LIMIT 1", tuple(params))
        return self._chat_item(rows[0]) if rows else None

    def get_contact_chats(self, jid: str, limit: int, offset: int) -> list[dict]:
        limit, offset = _page(limit, offset)
        vs = self.variants(jid)
        marks = ",".join("?" * len(vs))
        # IN (subquery) instead of a join: a chat appears once however many messages the contact sent in it
        rows = self._all(
            self._chat_sql(True) + f" WHERE c.jid IN ({marks}) "
            f"OR c.jid IN (SELECT chat_jid FROM messages WHERE sender IN ({marks})) "
            "ORDER BY c.last_message_time DESC, c.jid LIMIT ? OFFSET ?", (*vs, *vs, limit, offset))
        return [self._chat_item(r) for r in rows]

    def get_last_interaction(self, jid: str) -> dict | None:
        vs = self.variants(jid)
        marks = ",".join("?" * len(vs))
        rows = self._all(
            f"SELECT {_MSG_COLS} FROM messages m JOIN chats c ON m.chat_jid = c.jid "
            f"WHERE m.sender IN ({marks}) OR c.jid IN ({marks}) ORDER BY m.timestamp DESC, m.rowid DESC LIMIT 1",
            (*vs, *vs))
        return self._msg(rows[0]) if rows else None

    def list_messages(self, after: str | None, before: str | None, sender_phone_number: str | None,
                      chat_jid: str | None, query: str | None, limit: int, offset: int,
                      context_before: int = 0, context_after: int = 0) -> list[dict]:
        limit, offset = _page(limit, offset)
        where, params = [], []
        for col, op, val in (("m.timestamp", ">", _iso_arg(after, "after")),
                             ("m.timestamp", "<", _iso_arg(before, "before")),
                             ("m.chat_jid", "=", chat_jid)):
            if val:
                where.append(f"{col} {op} ?")
                params.append(val)
        if sender_phone_number:
            vs = self.variants(f"{digits(sender_phone_number)}@{DEFAULT_SERVER}")
            where.append(f"m.sender IN ({','.join('?' * len(vs))})")
            params += vs
        if query:
            where.append("m.content LIKE ? ESCAPE '\\'")
            params.append(_like(query))
        sql = f"SELECT {_MSG_COLS} FROM messages m JOIN chats c ON m.chat_jid = c.jid"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self._all(sql + " ORDER BY m.timestamp DESC, m.rowid DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        out = []
        for r in rows:
            item = self._msg(r)
            if context_before or context_after:
                item["context_before"], item["context_after"] = self._around(r[1], r[5], context_before, context_after)
            out.append(item)
        return out

    def get_message_context(self, message_id: str, before: int, after: int, chat_jid: str | None = None) -> dict:
        sql = f"SELECT {_MSG_COLS} FROM messages m JOIN chats c ON m.chat_jid = c.jid WHERE m.id = ?"
        params: tuple = (message_id,)
        if chat_jid:
            sql, params = sql + " AND m.chat_jid = ?", (message_id, chat_jid)
        rows = self._all(sql + " ORDER BY m.rowid LIMIT 1", params)
        if not rows:
            raise LookupError(f"message {message_id} not found")
        b, a = self._around(rows[0][1], rows[0][5], before, after)
        return {"message": self._msg(rows[0]), "before": b, "after": a}

    def get_media_ref(self, message_id: str, chat_jid: str) -> dict | None:
        rows = self._all("SELECT media_type, filename, file_length, raw FROM messages WHERE id = ? AND chat_jid = ?",
                         (message_id, chat_jid))
        if not rows or not rows[0][3]:
            return None
        return {"media_type": rows[0][0], "filename": rows[0][1], "file_length": rows[0][2], "raw": rows[0][3]}

    def _around(self, chat_jid: str, ts: str, before: int, after: int) -> tuple[list[dict], list[dict]]:
        base = f"SELECT {_MSG_COLS} FROM messages m JOIN chats c ON m.chat_jid = c.jid WHERE m.chat_jid = ? AND m.timestamp "
        prev = self._all(base + "< ? ORDER BY m.timestamp DESC LIMIT ?", (chat_jid, ts, _ctx(before)))
        nxt = self._all(base + "> ? ORDER BY m.timestamp ASC LIMIT ?", (chat_jid, ts, _ctx(after)))
        return [self._msg(r) for r in reversed(prev)], [self._msg(r) for r in nxt]
