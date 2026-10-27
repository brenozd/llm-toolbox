from whatsapp_mcp import jid


def test_canonical_digits_and_jids():
    assert jid.canonical("5511999990000") == "5511999990000@s.whatsapp.net"
    assert jid.canonical("5511999990000@s.whatsapp.net") == "5511999990000@s.whatsapp.net"
    assert jid.canonical("5511999990000.0:12@s.whatsapp.net") == "5511999990000@s.whatsapp.net"
    assert jid.canonical("120363000000000000@g.us") == "120363000000000000@g.us"
    assert jid.canonical("123456789012345@lid") == "123456789012345@lid"
    assert jid.canonical("5511@s.whatsapp.net") is None  # too short to be a phone number


def test_canonical_rejects():
    for bad in ("", "12345", "abc", "+5511999990000", "5511999990000@example.com", "5511999990000@s.whatsapp.net\n",
                "5511999990000.0:12", "5511@s.whatsapp.net", "12345@lid"):
        assert jid.canonical(bad) is None, bad


def test_norm_strips_device_and_agent():
    assert jid.norm("5511999990000.0:12@s.whatsapp.net") == "5511999990000@s.whatsapp.net"
    assert jid.norm("5511999990000:12@s.whatsapp.net") == "5511999990000@s.whatsapp.net"
    assert jid.norm("5511999990000") == "5511999990000"
    assert jid.norm("12345@lid") == "12345@lid"
    assert jid.norm("") == ""


def test_split_and_helpers():
    assert jid.split("12345@lid") == ("12345", "lid")
    assert jid.is_group("120363000000000000@g.us") and not jid.is_group("12345@lid")
    assert jid.digits("+55 (11) 99999-0000") == "5511999990000"
    try:
        jid.digits("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    test_canonical_digits_and_jids()
    test_canonical_rejects()
    test_norm_strips_device_and_agent()
    test_split_and_helpers()
    print("ok")
