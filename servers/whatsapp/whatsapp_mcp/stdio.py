"""Keep the MCP stdio channel private.

The whatsmeow Go core (and any stray print) writes to fd 1, which belongs to the transport.
At startup we dup fd 1 to a private descriptor, point fd 1 and sys.stdout at stderr, and hand
the saved descriptor to the transport only.
"""
from __future__ import annotations

import io
import os
import sys

import anyio
from mcp.server.stdio import stdio_server

# holds the original sys.stdout object: dropping it would close fd 1 (now a copy of stderr)
_keeper: list = []


def guard_stdout(fd: int = 1) -> int:
    """Move fd 1 (and sys.stdout) to stderr; return the private fd that now carries MCP."""
    saved = os.dup(fd)
    _keeper.append(sys.stdout)
    os.dup2(2, fd)
    sys.stdout = sys.stderr
    return saved


def run_stdio(mcp, channel_fd: int) -> None:
    """Run the server's stdio transport on `channel_fd` instead of fd 1.

    FastMCP.run() hardcodes sys.stdout for its transport, so we drive the same lowlevel server
    with an explicit output stream (mcp is pinned <2; see the README's upgrade notes).
    """
    stream = io.TextIOWrapper(os.fdopen(channel_fd, "wb", buffering=0, closefd=False), encoding="utf-8")

    async def main() -> None:
        async with stdio_server(stdout=anyio.wrap_file(stream)) as (read_stream, write_stream):
            # no public FastMCP API accepts a stream, hence the lowlevel server
            await mcp._mcp_server.run(
                read_stream, write_stream, mcp._mcp_server.create_initialization_options())

    anyio.run(main)
