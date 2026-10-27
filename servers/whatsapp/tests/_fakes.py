"""Shared fakes: the tools/server only need this small client interface."""
from __future__ import annotations


class FakeClient:
    def __init__(self, connected: bool = True, media: bytes = b"media-bytes"):
        self.connected = connected
        self.logged_in = connected
        self.media = media
        self.sent: list[tuple] = []
        self.downloaded: list[bytes] = []
        self.connect_calls = 0
        self.closed = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_logged_in(self) -> bool:
        return self.logged_in

    def own_jid(self):
        return "5511999990000@s.whatsapp.net"

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> None:
        self.closed = True

    def send_text(self, jid: str, text: str) -> dict:
        self.sent.append(("text", jid, text))
        return {"message_id": f"sent-{len(self.sent)}"}

    def send_file(self, jid: str, data: bytes, kind: str, filename: str) -> dict:
        self.sent.append((kind, jid, data, filename))
        return {"message_id": f"file-{len(self.sent)}"}

    def download(self, raw: bytes) -> bytes:
        self.downloaded.append(raw)
        return self.media
