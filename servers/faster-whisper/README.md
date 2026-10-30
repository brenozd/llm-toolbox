# faster-whisper-mcp

MCP server exposing speech-to-text transcription via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), over stdio.

> **Non-obvious:** the model loads lazily on the first `transcribe` call, not
> at server startup — the first transcription in a session is slower while
> the model downloads/initializes.

> **Non-obvious:** no weights are baked into the image. The model is downloaded
> from Hugging Face on first use into `/root/.cache/huggingface` inside the
> container, which is thrown away with `--rm`. On a slow link the first call can
> take minutes; the plugin entry mounts `${HOME}/.cache/huggingface` (the host HF cache, shared)
> so it is downloaded once. (`XDG_CACHE_HOME` is not expanded by the plugin launcher, so the path is fixed.)

## Config

No config file. Behavior is tuned with env vars, all optional:

| Var | Default | Notes |
|---|---|---|
| `WHISPER_MODEL` | `small` | Any faster-whisper model size (`tiny`, `base`, `small`, `medium`, …). `tiny` is ~4x faster but garbles pt-BR accents and identifiers (WER 0.40 vs 0.00 on short accented lines) — use it only for throwaway checks |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | e.g. `int8`, `float16` |

The container mounts `${HOME}:${HOME}:ro` (see plugin manifest) so
`audio_path` must be a host path under your home directory, readable from
inside the container.

## Dependency pins

`pyproject.toml` pins `faster-whisper>=1.2.1,<1.3` and `av>=11,<19`. Both are
load-bearing: faster-whisper 1.2.1 calls `av.open(..., metadata_errors="ignore")`
and PyAV **19 removed that kwarg**, so with `av` 19 every `transcribe` fails with
`open() got an unexpected keyword argument 'metadata_errors'`. Do not lift the
`<19` ceiling until faster-whisper ships the fix.

## Image

```bash
docker pull harbor.bzd.gg/bzd/faster-whisper-mcp:latest
```

To build locally instead:

```bash
docker build -t harbor.bzd.gg/bzd/faster-whisper-mcp:latest .
```

## Tests

`tests/test_contract.py` is plain-assert (also pytest-compatible); the runtime
image is distroless and has no Python tooling, so mount the tests into the
image and run them with the runtime interpreter:

```bash
docker build -t faster-whisper-mcp:dev .
docker run --rm -v "$PWD:/w:ro" --entrypoint /usr/bin/python3 faster-whisper-mcp:dev \
  -c "import sys; sys.path.insert(0,'/w'); import tests.test_contract as tc;
      [getattr(tc, n)() for n in dir(tc) if n.startswith('test_')]; print('ok')"
```

## Run

```json
{
  "mcpServers": {
    "faster-whisper": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "${HOME}:${HOME}:ro",
        "-v", "${HOME}/.cache/huggingface:/root/.cache/huggingface",
        "harbor.bzd.gg/bzd/faster-whisper-mcp:latest"
      ]
    }
  }
}
```

## Tools

| Tool | Description |
|---|---|
| `transcribe` | Transcribe a local audio file to text, with per-segment timestamps. Pass a BCP-47-ish `language` code (e.g. `en`, `pt`) to skip auto-detection |
