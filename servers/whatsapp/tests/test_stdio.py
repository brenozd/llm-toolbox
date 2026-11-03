"""MCP stdout must carry JSON-RPC only, even when native code / a stray print writes to fd 1."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = Path(__file__).with_name("_serve_probe.py")
JUNK = ("JUNK-NATIVE-TO-FD1", "JUNK-PYTHON-PRINT", "JUNK-STDOUT-WRITE")

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
INITED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
CALL = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "whatsapp_list_chats", "arguments": {}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def run_probe():
    # stdin stays open until the tools/list answer arrives, like a real client; EOF would cancel it
    with tempfile.TemporaryDirectory() as d:
        proc = subprocess.Popen([sys.executable, str(PROBE), d], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        out = []
        try:
            for m in (INIT, INITED, LIST):
                proc.stdin.write(json.dumps(m) + "\n")
                proc.stdin.flush()
            for line in proc.stdout:
                out.append(line)
                if line.strip() and json.loads(line).get("id") == 2:
                    break
        finally:
            rest, err = proc.communicate(timeout=60)  # closes stdin itself; closing it first breaks 3.12
    proc.stdout_text = "".join(out) + rest
    proc.stderr_text = err
    return proc


def test_stdout_is_pure_json_rpc():
    proc = run_probe()
    assert proc.returncode == 0, proc.stderr_text
    lines = [line for line in proc.stdout_text.splitlines() if line.strip()]
    assert lines, f"no JSON-RPC response; stderr={proc.stderr_text}"
    for line in lines:
        payload = json.loads(line)  # any junk on stdout fails here
        assert payload.get("jsonrpc") == "2.0", line
    for junk in JUNK:
        assert junk not in proc.stdout_text, f"{junk} leaked into stdout"
        assert junk in proc.stderr_text, f"{junk} was not redirected to stderr"


def test_handshake_lists_tools():
    proc = run_probe()
    payloads = [json.loads(line) for line in proc.stdout_text.splitlines() if line.strip()]
    listed = [p for p in payloads if p.get("id") == 2]
    assert listed, payloads
    names = [t["name"] for t in listed[0]["result"]["tools"]]
    assert "whatsapp_check_connection" in names, names
    assert "whatsapp_send_message" not in names, names
    assert any(p.get("id") == 1 and "result" in p for p in payloads), payloads


def test_empty_list_result_is_an_object():
    # stdin stays open until the answer arrives, like a real client; EOF would cancel the call
    with tempfile.TemporaryDirectory() as d:
        proc = subprocess.Popen([sys.executable, str(PROBE), d], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        try:
            for m in (INIT, INITED, CALL):
                proc.stdin.write(json.dumps(m) + "\n")
                proc.stdin.flush()
            call = None
            for line in proc.stdout:
                if json.loads(line).get("id") == 3:
                    call = json.loads(line)
                    break
        finally:
            proc.stdin.close()
            proc.wait(timeout=30)
    blocks = call["result"]["content"]
    assert len(blocks) == 1 and json.loads(blocks[0]["text"]) == {"chats": []}, call


if __name__ == "__main__":
    test_stdout_is_pure_json_rpc()
    test_handshake_lists_tools()
    test_empty_list_result_is_an_object()
    print("ok")
