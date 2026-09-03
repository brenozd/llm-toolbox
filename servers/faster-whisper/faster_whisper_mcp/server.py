from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from faster_whisper import WhisperModel
from mcp.server.fastmcp import Context, FastMCP

from . import tools as t
from .config import load_config


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    # Lazy-load model on first use, not on server startup
    ctx = {"model": None}
    yield ctx


mcp = FastMCP("faster-whisper", lifespan=lifespan)


def _model(ctx: Context) -> WhisperModel:
    ctx_dict = ctx.request_context.lifespan_context
    if ctx_dict["model"] is None:
        config = load_config()
        ctx_dict["model"] = WhisperModel(config.model_size, device=config.device, compute_type=config.compute_type)
    return ctx_dict["model"]


@mcp.tool()
def transcribe(ctx: Context, audio_path: str, language: str | None = None) -> object:
    """Transcribe a local audio file to text using faster-whisper. Pass a BCP-47-ish language code (e.g. 'en', 'pt') to skip auto-detection."""
    return t.transcribe(_model(ctx), audio_path, language)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
