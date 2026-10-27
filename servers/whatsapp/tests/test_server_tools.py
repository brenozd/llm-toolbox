import anyio
from whatsapp_mcp.config import WhatsAppConfig
from whatsapp_mcp.server import UNTRUSTED, build_server

READ_TOOLS = (
    "whatsapp_search_contacts", "whatsapp_list_chats", "whatsapp_get_chat", "whatsapp_get_direct_chat_by_contact",
    "whatsapp_get_contact_chats", "whatsapp_get_last_interaction", "whatsapp_list_messages",
    "whatsapp_get_message_context", "whatsapp_download_media",
)
SEND_TOOLS = ("whatsapp_send_message", "whatsapp_send_file", "whatsapp_send_audio_message")


def tools_of(config: WhatsAppConfig) -> dict:
    mcp = build_server(config, client_factory=lambda cfg, store: None)
    return {t.name: t for t in anyio.run(mcp.list_tools)}


def test_read_only_registers_no_send_tools():
    names = tools_of(WhatsAppConfig(data_dir="/tmp/wa-test", media_dir="/tmp"))
    assert "whatsapp_check_connection" in names
    for tool in READ_TOOLS:
        assert tool in names, sorted(names)
    for tool in SEND_TOOLS:
        assert tool not in names, sorted(names)


def test_allow_send_registers_send_tools():
    names = tools_of(WhatsAppConfig(data_dir="/tmp/wa-test", media_dir="/tmp", allow_send=True))
    for tool in SEND_TOOLS:
        assert tool in names, sorted(names)
    assert len(names) == len(READ_TOOLS) + len(SEND_TOOLS) + 1


def test_message_content_is_flagged_untrusted():
    tools = tools_of(WhatsAppConfig(data_dir="/tmp/wa-test", media_dir="/tmp"))
    for name in READ_TOOLS:
        assert tools[name].description.endswith(UNTRUSTED), (name, tools[name].description)
    assert "connected" in tools["whatsapp_check_connection"].description.lower()
    # send results are ours, not third-party data
    send = tools_of(WhatsAppConfig(data_dir="/tmp/wa-test", media_dir="/tmp", allow_send=True))
    for name in SEND_TOOLS:
        assert UNTRUSTED not in send[name].description, name


if __name__ == "__main__":
    test_read_only_registers_no_send_tools()
    test_allow_send_registers_send_tools()
    test_message_content_is_flagged_untrusted()
    print("ok")
