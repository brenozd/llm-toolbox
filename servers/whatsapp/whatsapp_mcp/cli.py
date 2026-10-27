from __future__ import annotations

import argparse
import os
import sys

from .client import NeonizeClient, log
from .config import ConfigError, WhatsAppConfig, load_config
from .store import Store

LOGIN_TIMEOUT = 180.0


def print_qr(data: bytes) -> None:
    """Terminal QR: stderr, so a redirected stdout can never swallow the code."""
    import segno

    segno.make_qr(data.decode()).terminal(compact=True, out=sys.stderr)


def run_login(config: WhatsAppConfig) -> int:
    store = Store(config.data_dir)
    client = NeonizeClient(config.data_dir, store, qr=print_qr)
    try:
        client.connect()
        if client.wait_connected(LOGIN_TIMEOUT) or client.is_logged_in:
            log("paired; the session is stored in the data dir")
            return 0
        log(f"login timed out after {int(LOGIN_TIMEOUT)}s")
        return 1
    finally:
        client.close()
        store.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="whatsapp-mcp", description="WhatsApp MCP server (stdio).")
    ap.add_argument("command", nargs="?", choices=("serve", "login"), default="serve",
                    help="serve: run the MCP server (default); login: pair this device by scanning a QR code")
    args = ap.parse_args(argv)
    os.umask(0o077)
    try:
        config = load_config()
    except ConfigError as e:
        sys.exit(f"whatsapp-mcp: {e}")
    if args.command == "login":
        rc = run_login(config)
        sys.stderr.flush()
        os._exit(rc)  # neonize's non-daemon worker would keep the process alive
    from .server import serve

    serve(config)
    sys.stderr.flush()
    os._exit(0)  # same: stdin EOF must end the process


if __name__ == "__main__":
    main()
