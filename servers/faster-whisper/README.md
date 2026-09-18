# faster-whisper-mcp

MCP server exposing speech-to-text transcription via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), over stdio.

> **Non-obvious:** the model loads lazily on the first `transcribe` call, not
> at server startup — the first transcription in a session is slower while
> the model downloads/initializes.

## Config

No config file. Behavior is tuned with env vars, all optional:

| Var | Default | Notes |
|---|---|---|
| `WHISPER_MODEL` | `tiny` | Any faster-whisper model size (`base`, `small`, `medium`, …) |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | e.g. `int8`, `float16` |

The container mounts `${HOME}:${HOME}:ro` (see plugin manifest) so
`audio_path` must be a host path under your home directory, readable from
inside the container.

## Image

```bash
docker pull registry.bzd.gg/bzd/faster-whisper-mcp:latest
```

To build locally instead:

```bash
docker build -t registry.bzd.gg/bzd/faster-whisper-mcp:latest .
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
        "registry.bzd.gg/bzd/faster-whisper-mcp:latest"
      ]
    }
  }
}
```

## Tools

| Tool | Description |
|---|---|
| `transcribe` | Transcribe a local audio file to text, with per-segment timestamps. Pass a BCP-47-ish `language` code (e.g. `en`, `pt`) to skip auto-detection |
