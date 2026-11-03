from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from huggingface_hub import hf_hub_download
import transcribe_cpp
from mcp.server.fastmcp import Context, FastMCP

from . import tools as t
from .config import load_config


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    # Lazy-load model on first use, not on server startup
    ctx = {"model": None}
    yield ctx


mcp = FastMCP("audio-transcribe", lifespan=lifespan)


def _session(ctx: Context):
    ctx_dict = ctx.request_context.lifespan_context
    if ctx_dict["model"] is None:
        config = load_config()
        model = transcribe_cpp.Model(hf_hub_download(config.repo, config.filename))
        ctx_dict["model"] = (model, model.session())
    return ctx_dict["model"][1]


@mcp.tool()
def transcribe(ctx: Context, audio_path: str, language: str | None = None, output_format: str = "json") -> object:
    """Transcribe a local audio file (ogg/opus, m4a, mp3, wav...) to text with Parakeet. language: optional code such as 'pt' or 'en' (auto-detected when omitted). output_format: 'json' (60 s segments with timestamps, default) or 'text'."""
    return t.transcribe(_session(ctx), audio_path, language, output_format)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
