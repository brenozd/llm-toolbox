"""Tool implementations. Every message-derived string returned here is untrusted third-party data."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path, PurePosixPath

from . import audio, media
from .config import WhatsAppConfig
from .jid import canonical
from .store import Store, iso_utc

_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".3gp"}


def require_send(config: WhatsAppConfig) -> None:
    """The tools are only registered when allow_send is on; check again so a stale registration cannot send."""
    if not config.allow_send:
        raise ValueError("sending is disabled (allow_send=false)")


def check_recipient(config: WhatsAppConfig, recipient: str) -> str:
    """Canonical JID for an allowed recipient, or ValueError."""
    jid = canonical(recipient or "")
    if jid is None:
        raise ValueError("recipient must be a phone number (6-15 digits) or a JID")
    if config.allowed_recipients and jid not in config.allowed_recipients:
        raise ValueError("recipient is not in allowed_recipients")
    return jid


def resolve_media(config: WhatsAppConfig, rel: str) -> Path:
    """Map a media_dir-relative path to a real file inside media_dir, or raise."""
    if not rel or "\0" in rel:
        raise ValueError("media_path must be a relative path inside the media dir")
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("media_path must be relative to the media dir and contain no '..'")
    root = Path(config.media_dir).resolve()
    full = (root / rel).resolve()
    if full != root and not full.is_relative_to(root):
        raise ValueError("media_path must stay inside the media dir")
    if not full.is_file():
        raise ValueError("file not found inside the media dir")
    if full.stat().st_size > config.max_media_bytes:
        raise ValueError("file exceeds max_media_bytes")
    return full


def _read(config: WhatsAppConfig, rel: str) -> tuple[Path, bytes]:
    path = resolve_media(config, rel)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)  # no path re-resolution between check and read
    with os.fdopen(fd, "rb") as fh:
        data = fh.read(config.max_media_bytes + 1)
    if len(data) > config.max_media_bytes:
        raise ValueError("file exceeds max_media_bytes")
    return path, data


def _sender(client) -> str:
    return getattr(client, "own_jid", lambda: None)() or "me"


def _record(store: Store, client, jid: str, *, content: str = "", media_type: str | None = None,
            filename: str | None = None, file_length: int | None = None, message_id: str | None) -> None:
    """Store what we sent (upstream never did) so it shows up in later reads."""
    if not message_id:
        return
    store.add_message(id=message_id, chat_jid=jid, sender=_sender(client), content=content,
                      timestamp=iso_utc(time.time()), is_from_me=True, media_type=media_type,
                      filename=filename, file_length=file_length)


# -- reads (store only)
def check_connection(config: WhatsAppConfig, client) -> dict:
    return {
        "connected": bool(client.is_connected),
        "logged_in": bool(client.is_logged_in),
        "allow_send": config.allow_send,
    }


def search_contacts(store: Store, query: str) -> list[dict]:
    with store.reader() as r:
        return r.search_contacts(query or "")


def list_chats(store: Store, query: str | None = None, limit: int = 20, offset: int = 0,
               include_last_message: bool = True, sort_by: str = "last_active") -> list[dict]:
    with store.reader() as r:
        return r.list_chats(query, limit, offset, include_last_message, sort_by)


def get_chat(store: Store, chat_jid: str, include_last_message: bool = True) -> dict:
    with store.reader() as r:
        return r.get_chat(chat_jid, include_last_message) or {"found": False}


def get_direct_chat_by_contact(store: Store, phone_number: str) -> dict:
    with store.reader() as r:
        return r.get_direct_chat_by_contact(phone_number) or {"found": False}


def get_contact_chats(store: Store, jid: str, limit: int = 20, offset: int = 0) -> list[dict]:
    with store.reader() as r:
        return r.get_contact_chats(jid, limit, offset)


def get_last_interaction(store: Store, jid: str) -> dict:
    with store.reader() as r:
        return r.get_last_interaction(jid) or {"found": False}


def list_messages(store: Store, after: str | None = None, before: str | None = None,
                  sender_phone_number: str | None = None, chat_jid: str | None = None, query: str | None = None,
                  limit: int = 20, offset: int = 0, include_context: bool = False,
                  context_before: int = 1, context_after: int = 1) -> list[dict]:
    cb, ca = (context_before, context_after) if include_context else (0, 0)
    with store.reader() as r:
        return r.list_messages(after, before, sender_phone_number, chat_jid, query, limit, offset, cb, ca)


def get_message_context(store: Store, message_id: str, before: int = 5, after: int = 5,
                        chat_jid: str | None = None) -> dict:
    with store.reader() as r:
        return r.get_message_context(message_id, before, after, chat_jid)


# -- media
def download_media(config: WhatsAppConfig, store: Store, client, message_id: str, chat_jid: str) -> dict:
    if not message_id or not chat_jid:
        raise ValueError("message_id and chat_jid are required")
    with store.reader() as r:
        ref = r.get_media_ref(message_id, chat_jid)
    if ref is None:
        raise LookupError("no downloadable media stored for that message")
    length = ref["file_length"] or 0
    # cap before the download; the length is sender-declared, so unknown (0) is refused too.
    # shortcut: neonize's download_any buffers in RAM, so a lying sender can still cost up to one blob.
    if length <= 0 or length > config.max_media_bytes:
        raise ValueError("media exceeds max_media_bytes")
    data = client.download(ref["raw"])
    if len(data) > config.max_media_bytes:
        raise ValueError("media exceeds max_media_bytes")
    name = ref["filename"] or ref["media_type"] or "file"
    path = media.write_download(config.data_dir, message_id, name, data)
    return {"path": str(path), "media_type": ref["media_type"], "filename": ref["filename"],
            "size": len(data), "content_is_untrusted": True}


# -- sends (only registered when allow_send is on)
def send_message(config: WhatsAppConfig, store: Store, client, recipient: str, message: str) -> dict:
    require_send(config)
    jid = check_recipient(config, recipient)
    if not (message or "").strip():
        raise ValueError("message must not be empty")
    result = client.send_text(jid, message)
    _record(store, client, jid, content=message, message_id=result.get("message_id"))
    return {**result, "success": True, "recipient": jid}


def send_file(config: WhatsAppConfig, store: Store, client, recipient: str, media_path: str) -> dict:
    require_send(config)
    jid = check_recipient(config, recipient)
    path, data = _read(config, media_path)
    suffix = path.suffix.lower()
    kind = "image" if suffix in _IMAGE else "video" if suffix in _VIDEO else "document"
    result = client.send_file(jid, data, kind, path.name)
    _record(store, client, jid, media_type=kind, filename=path.name, file_length=len(data),
            message_id=result.get("message_id"))
    return {**result, "success": True, "recipient": jid, "media_type": kind}


def send_audio_message(config: WhatsAppConfig, store: Store, client, recipient: str, media_path: str) -> dict:
    require_send(config)
    jid = check_recipient(config, recipient)
    src = resolve_media(config, media_path)
    # always transcode: the voice-note container is ogg/opus, and the temp file must not sit next to the source
    with tempfile.TemporaryDirectory(prefix="wa-voice-") as tmp:
        dst = Path(tmp) / "voice.ogg"
        audio.convert_to_opus_ogg(src, dst)
        data = dst.read_bytes()
        if len(data) > config.max_media_bytes:
            raise ValueError("converted audio exceeds max_media_bytes")
        result = client.send_file(jid, data, "voice", "voice.ogg")
    _record(store, client, jid, media_type="audio", filename="voice.ogg", file_length=len(data),
            message_id=result.get("message_id"))
    return {**result, "success": True, "recipient": jid, "media_type": "audio"}
