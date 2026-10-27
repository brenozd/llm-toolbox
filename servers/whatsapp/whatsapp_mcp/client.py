"""neonize (whatsmeow Go core via ctypes) wrapper.

Event handlers are plain functions over proto events so they can be tested without a connection.
Everything the tools need is behind the small `Client` interface below, which the tests fake.
"""
from __future__ import annotations

import mimetypes
import os
import sys
import threading
from pathlib import Path

from neonize.client import NewClient
from neonize.events import (
    ConnectedEv,
    DisconnectedEv,
    HistorySyncEv,
    LoggedOutEv,
    MessageEv,
    PairStatusEv,
)
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from neonize.utils.jid import Jid2String, build_jid

from .jid import norm, split
from .store import SESSION_DB, Store, iso_utc

UUID = b"whatsapp-mcp"
_MEDIA = (("imageMessage", "image"), ("videoMessage", "video"), ("audioMessage", "audio"),
          ("documentMessage", "document"), ("stickerMessage", "sticker"))


def log(msg: str) -> None:
    """stderr only: stdout belongs to the MCP transport."""
    print(f"whatsapp-mcp: {msg}", file=sys.stderr, flush=True)


def jid_str(j) -> str:
    """Non-AD `user@server` string of a proto JID."""
    return Jid2String(j) if getattr(j, "User", None) else (j.Server or "")


def unix_seconds(ts: int) -> int:
    """whatsmeow timestamps are unix milliseconds."""
    return ts // 1000 if ts > 10**11 else ts


def media_of(m) -> tuple[str, object] | None:
    """(kind, sub-message) for the media carried by a message, if any."""
    for field, kind in _MEDIA:
        if m.HasField(field):
            return kind, getattr(m, field)
    return None


_WRAPPERS = ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "documentWithCaptionMessage")


def unwrap(m):
    """Peel disappearing/view-once/caption wrappers; their payload is the real message."""
    for _ in range(4):
        w = next((f for f in _WRAPPERS if m.HasField(f) and m.__getattribute__(f).HasField("message")), None)
        if w is None:
            break
        m = getattr(m, w).message
    return m


def extract(m) -> tuple[str, str | None, str | None, int | None, bytes | None]:
    """waE2E message -> (content, media_type, filename, file_length, raw media sub-message)."""
    m = unwrap(m)
    if m.conversation:
        return m.conversation, None, None, None, None
    if m.HasField("extendedTextMessage"):
        return m.extendedTextMessage.text, None, None, None, None
    found = media_of(m)
    if not found:
        return "", None, None, None, None
    kind, sub = found
    mime = (sub.mimetype or "").split(";")[0].strip()
    ext = mimetypes.guess_extension(mime) if mime else None
    if kind == "audio" and mime in ("audio/ogg", "audio/opus"):
        ext = ".ogg"
    filename = getattr(sub, "fileName", "") or f"{kind}{ext or ''}"
    # keep only the media sub-message: that is all download_any needs
    raw = type(m)(**{kind + "Message": sub}).SerializeToString()
    return getattr(sub, "caption", "") or "", kind, filename, sub.fileLength, raw


def _store(store: Store, *, mid: str, chat: str, sender: str, ts: int, from_me: bool, m,
           chat_name: str | None = None) -> None:
    if not mid or not chat:
        return
    content, kind, filename, length, raw = extract(m)
    if not (content or kind):
        return
    store.add_message(id=mid, chat_jid=chat, sender=sender, content=content, timestamp=iso_utc(unix_seconds(ts)),
                      is_from_me=from_me, chat_name=chat_name, media_type=kind, filename=filename,
                      file_length=length, raw=raw)


def on_message(store: Store, ev, own_jid: str | None = None) -> None:
    src = ev.Info.MessageSource
    chat = norm(jid_str(src.Chat))
    sender = norm(jid_str(src.Sender))
    if not sender:
        sender = (own_jid or "me") if src.IsFromMe else chat
    # a DM's push name is the other party's; our own messages carry ours
    name = ev.Info.Pushname if ev.Info.Pushname and not src.IsFromMe and not src.IsGroup else None
    _store(store, mid=ev.Info.ID, chat=chat, sender=sender, ts=ev.Info.Timestamp, from_me=src.IsFromMe,
           m=ev.Message, chat_name=name)


def on_history(store: Store, ev, own_jid: str | None = None) -> None:
    for conv in ev.Data.conversations:
        chat = norm(conv.ID)
        if not chat:
            continue
        store.upsert_chat(chat, conv.name or conv.displayName or None, None)
        for hm in conv.messages:
            wm = hm.message
            participant = wm.key.participant or wm.participant
            sender = norm(participant) if participant else (own_jid or "me") if wm.key.fromMe else chat
            _store(store, mid=wm.key.ID, chat=chat, sender=sender, ts=wm.messageTimestamp,
                   from_me=wm.key.fromMe, m=wm.message)


class NeonizeClient:
    """The real client: one process, Go core loaded in-process, connect runs in a thread."""

    def __init__(self, data_dir: str | Path, store: Store | None = None, qr=None):
        self.store = store
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.session_path = self.data_dir / SESSION_DB
        os.close(os.open(self.session_path, os.O_CREAT | os.O_RDWR, 0o600))
        os.chmod(self.data_dir, 0o700)
        os.chmod(self.session_path, 0o600)
        self._nc = NewClient(str(self.session_path), uuid=UUID.decode())
        self.connected = threading.Event()
        self.paired = threading.Event()
        self._thread: threading.Thread | None = None
        # serve must never print the pairing QR into the log stream
        qr = qr or (lambda _data: log("not paired: run `whatsapp-mcp login`"))
        self._nc.event.qr(lambda _c, data: qr(data))
        self._register()

    # -- handlers
    def _register(self) -> None:
        def guard(fn, name: str):
            def run(_client, ev):
                try:
                    fn(ev)
                except Exception as exc:  # a handler error must not escape into the Go callback thread
                    log(f"{name} handler failed: {type(exc).__name__}")
            return run

        def store_call(fn):
            def run(ev):
                if self.store is not None:
                    fn(ev)
            return run

        reg = self._nc.event
        reg(MessageEv)(guard(store_call(lambda e: on_message(self.store, e, self.own_jid())), "message"))
        reg(HistorySyncEv)(guard(store_call(lambda e: on_history(self.store, e, self.own_jid())), "history"))
        reg(ConnectedEv)(guard(lambda _e: (self.connected.set(), log("connected")), "connected"))
        reg(PairStatusEv)(guard(lambda _e: (self.paired.set(), log("paired")), "pair"))
        reg(LoggedOutEv)(guard(lambda _e: log("logged out; run `whatsapp-mcp login` again"), "logout"))
        reg(DisconnectedEv)(guard(lambda _e: (self.connected.clear(), log("disconnected")), "disconnected"))

    # -- lifecycle
    def connect(self) -> None:
        """Start connecting in the background: neonize's connect() blocks until stopped."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="neonize", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._nc.connect()
        except Exception as exc:
            log(f"connection error: {type(exc).__name__}: {exc}")
        finally:
            self.connected.clear()

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)

    def close(self) -> None:
        try:
            self._nc.stop()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    # -- state
    @property
    def is_connected(self) -> bool:
        try:
            return bool(self._nc.is_connected)
        except Exception:
            return False

    @property
    def is_logged_in(self) -> bool:
        try:
            return bool(self._nc.is_logged_in)
        except Exception:
            return False

    def own_jid(self) -> str | None:
        me = getattr(self._nc, "me", None)
        jid = getattr(me, "JID", None) if me is not None else None
        return norm(jid_str(jid)) if jid is not None else None

    # -- actions
    @staticmethod
    def _to(jid: str):
        user, server = split(jid)
        return build_jid(user, server)

    def send_text(self, jid: str, text: str) -> dict:
        return {"message_id": self._nc.send_message(self._to(jid), text).ID}

    def send_file(self, jid: str, data: bytes, kind: str, filename: str) -> dict:
        """kind: image | video | document | audio | voice (ogg/opus voice note)."""
        to = self._to(jid)
        if kind == "image":
            resp = self._nc.send_image(to, data)
        elif kind == "video":
            resp = self._nc.send_video(to, data)
        elif kind in ("audio", "voice"):
            resp = self._nc.send_audio(to, data, ptt=kind == "voice")
        else:
            resp = self._nc.send_document(to, data, filename=filename)
        return {"message_id": resp.ID}

    def download(self, raw: bytes) -> bytes:
        data = self._nc.download_any(Message.FromString(raw))
        if data is None:
            raise RuntimeError("the server returned no media for that message")
        return data
