import json
import tempfile
from pathlib import Path

from whatsapp_mcp.config import ConfigError, WhatsAppConfig, load_config


def bad(raw, needle):
    try:
        WhatsAppConfig.from_dict(raw)
    except ConfigError as e:
        assert needle in str(e), e
    else:
        raise AssertionError(f"expected ConfigError for {raw}")


def test_defaults_and_valid():
    c = WhatsAppConfig.from_dict({})
    assert c.allow_send is False and c.allowed_recipients == () and c.data_dir == "/data"
    assert c.max_media_bytes == 64 * 1024 * 1024
    c = WhatsAppConfig.from_dict({"allow_send": True, "allowed_recipients": ["5511999990000", "5511999990001@s.whatsapp.net"]})
    assert c.allow_send and len(c.allowed_recipients) == 2


def test_allowlist_is_normalized():
    # the digits form and the JID form of the same number must compare equal
    c = WhatsAppConfig.from_dict({"allowed_recipients": ["5511999990000", "5511999990001.0:2@s.whatsapp.net"]})
    assert c.allowed_recipients == ("5511999990000@s.whatsapp.net", "5511999990001@s.whatsapp.net"), c.allowed_recipients
    c = WhatsAppConfig.from_dict({"allowed_recipients": ["123456789012345@lid", "120363000000000000@g.us"]})
    assert c.allowed_recipients == ("123456789012345@lid", "120363000000000000@g.us")


def test_rejects():
    bad({"nope": 1}, "unknown config key")
    bad({"allow_send": "yes"}, "allow_send")
    bad({"max_media_bytes": 0}, "max_media_bytes")
    bad({"max_media_bytes": True}, "max_media_bytes")
    bad({"data_dir": 5}, "data_dir")
    bad({"allowed_recipients": "123456"}, "allowed_recipients")
    bad({"allowed_recipients": ["+55 11"]}, "invalid entries")
    bad({"allowed_recipients": ["5511999990000@example.com"]}, "invalid entries")
    bad({"allowed_recipients": ["12345"]}, "invalid entries")
    bad([], "JSON object")


def test_load_config():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        try:
            load_config(p)
        except ConfigError as e:
            assert "not found" in str(e)
        p.write_text("{")
        try:
            load_config(p)
        except ConfigError as e:
            assert "not valid JSON" in str(e)
        p.write_text(json.dumps({"allow_send": True}))
        assert load_config(p).allow_send


if __name__ == "__main__":
    test_defaults_and_valid()
    test_allowlist_is_normalized()
    test_rejects()
    test_load_config()
    print("ok")
