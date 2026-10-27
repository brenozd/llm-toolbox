"""Helper for test_stdio.py: run `serve` with a fake client that pollutes fd 1.

Not a test itself (the test runner only picks up test_*.py).
"""
import os
import sys

from whatsapp_mcp import server as srv
from whatsapp_mcp.config import WhatsAppConfig


class NoisyClient:
    """Writes junk the way the Go core / an accidental print would."""

    @property
    def is_connected(self):
        return True

    @property
    def is_logged_in(self):
        return True

    def own_jid(self):
        return None

    def connect(self):
        os.write(1, b"JUNK-NATIVE-TO-FD1\n")
        print("JUNK-PYTHON-PRINT")
        sys.stdout.write("JUNK-STDOUT-WRITE\n")
        os.write(2, b"JUNK-TO-STDERR\n")

    def close(self):
        pass


if __name__ == "__main__":
    cfg = WhatsAppConfig(data_dir=sys.argv[1], media_dir=sys.argv[1])
    srv.serve(cfg, client_factory=lambda config, store: NoisyClient())
