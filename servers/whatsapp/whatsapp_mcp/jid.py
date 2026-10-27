"""JID helpers, mirroring whatsmeow's ParseJID/ToNonAD: `user[.agent][:device]@server`."""
from __future__ import annotations

import re

DEFAULT_SERVER = "s.whatsapp.net"
GROUP_SERVER = "g.us"
SERVERS = (DEFAULT_SERVER, "lid", GROUP_SERVER, "broadcast", "newsletter")

_PHONE = re.compile(r"\d{6,15}")
_JID = re.compile(r"(?P<user>\d+)(?:\.\d+)?(?::\d+)?@(?P<server>[a-z][a-z.\-]*)")
_USER = re.compile(r"(?P<user>\d+)(?:\.\d+)?(?::\d+)?$")


def norm(value: str) -> str:
    """Strip agent/device (`user.agent:device@server`) and keep `user@server`; lenient."""
    user, _, server = (value or "").partition("@")
    m = _USER.match(user)
    if m:
        user = m.group("user")
    return f"{user}@{server}" if server else user


def _user_ok(user: str, server: str) -> bool:
    # phones and LIDs are 6-15 digits; group/newsletter ids are longer
    return 6 <= len(user) <= (15 if server in (DEFAULT_SERVER, "lid") else 30)


def canonical(value: str) -> str | None:
    """Digits (6-15) or a valid JID -> non-AD `user@server`; None when invalid."""
    if _PHONE.fullmatch(value):
        return f"{value}@{DEFAULT_SERVER}"
    m = _JID.fullmatch(value)
    if m and m["server"] in SERVERS and _user_ok(m["user"], m["server"]):
        return f'{m["user"]}@{m["server"]}'
    return None


def split(jid: str) -> tuple[str, str]:
    user, _, server = jid.partition("@")
    return user, server


def is_group(jid: str) -> bool:
    return split(jid)[1] == GROUP_SERVER


def digits(value: str) -> str:
    d = "".join(ch for ch in (value or "") if ch.isdigit())
    if not d:
        raise ValueError("phone number must contain digits")
    return d
