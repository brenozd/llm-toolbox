# audio-transcribe-mcp

MCP server exposing speech-to-text transcription via NVIDIA Parakeet-TDT 0.6B v3 running on
[transcribe-cpp](https://github.com/handy-computer/transcribe.cpp) (ggml, CPU), over stdio. Formerly `faster-whisper-mcp` (renamed in 0.3.0).

> **Non-obvious:** the model loads lazily on the first `transcribe` call, not
> at server startup — the first transcription in a session is slower while
> the model downloads/initializes.

> **Non-obvious:** the model (`parakeet-tdt-0.6b-v3-Q8_0.gguf`, ~740 MB) is downloaded from
> Hugging Face into the mounted cache on first use; the image has no weights.

> **Non-obvious:** why Parakeet and not Whisper. On 80 public pt-BR clips (FLEURS + Common Voice,
> read speech, ~12 min) plus 20 with 10 s of silence inserted, 12 CPU threads: Parakeet WER 0.055 / 0.057
> in 46 s; faster-whisper `large-v3-turbo` 0.049 / 0.041 in 644 s; `small` 0.093 / 0.114 in 260 s.
> Silero VAD made `small` worse (0.121). Not measured on noisy real-world audio.

> **Non-obvious:** audio is cut into fixed 60 s windows (a 640 s buffer segfaulted the native
> engine), so a word on a boundary can be split; there is no `initial_prompt`/hotwords, Parakeet has none.

No config file. Behavior is tuned with env vars, all optional:

| Var | Default | Notes |
|---|---|---|
| `ASR_MODEL_REPO` | `handy-computer/parakeet-tdt-0.6b-v3-gguf` | Hugging Face repo with the GGUF |
| `ASR_MODEL_FILE` | `parakeet-tdt-0.6b-v3-Q8_0.gguf` | File in that repo (`Q4_K_M` is 485 MB, unmeasured) |

The container mounts `${HOME}:${HOME}:ro` (see plugin manifest) so
`audio_path` must be a host path under your home directory, readable from
inside the container.

## Dependency pins

`transcribe-cpp==0.2.3` is pinned exactly: it is a 0.x API and the native library ships separately.

## Image

```bash
docker pull harbor.bzd.gg/bzd/audio-transcribe-mcp:latest
```

To build locally instead:

```bash
docker build -t harbor.bzd.gg/bzd/audio-transcribe-mcp:latest .
```

## Tests

`tests/test_contract.py` is plain-assert (also pytest-compatible); the runtime
image is distroless and has no Python tooling, so mount the tests into the
image and run them with the runtime interpreter:

```bash
docker build -t audio-transcribe-mcp:dev .
docker run --rm -v "$PWD:/w:ro" --entrypoint /usr/bin/python3 audio-transcribe-mcp:dev \
  -c "import sys; sys.path.insert(0,'/w'); import tests.test_contract as tc;
      [getattr(tc, n)() for n in dir(tc) if n.startswith('test_')]; print('ok')"
```

## Run

```json
{
  "mcpServers": {
    "audio-transcribe": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "${HOME}:${HOME}:ro",
        "-v", "${HOME}/.cache/huggingface:/root/.cache/huggingface",
        "harbor.bzd.gg/bzd/audio-transcribe-mcp:latest"
      ]
    }
  }
}
```

## Tools

| Tool | Description |
|---|---|
| `transcribe` | Transcribe a local audio file (ogg/opus, m4a, mp3, wav…) to text. `language` is optional (e.g. `pt`); `output_format` is `json` (60 s segments with timestamps, default) or `text` |
