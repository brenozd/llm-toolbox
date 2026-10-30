# Build stage on the Python the runtime ships: distroless python3-debian12 is CPython 3.11, so the
# compiled wheels (ctranslate2, av, tokenizers) match the interpreter that loads them.
FROM python:3.11-slim-bookworm AS build

# onnxruntime only backs Silero VAD, and transcribe() never passes vad_filter — it is a 67 MB
# transitive dependency we can leave out. Uninstalled here, in the builder's real site-packages
# (a --prefix tree is not on sys.path, so an uninstall there would be a silent no-op).
WORKDIR /app
COPY pyproject.toml ./
COPY faster_whisper_mcp ./faster_whisper_mcp
RUN pip install --no-cache-dir . \
 && pip uninstall -y onnxruntime sympy mpmath coloredlogs humanfriendly flatbuffers

# Runtime: distroless python3 instead of python:3.12-slim — 53 MB vs 120 MB, and it drops the
# gcc/g++/dpkg-dev toolchain layer a runtime never uses. The console script is not copied; the
# package is run as a module (same main()). No model weights are baked in: faster-whisper fetches
# them into the default HF cache on first use, so the image stays small.
FROM gcr.io/distroless/python3-debian12@sha256:2fdb05402a2cf21cf78fdb3ba4c5db167241e9e498140f5bf689d7efb773731f

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/lib/python3/dist-packages
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

VOLUME ["/audio"]
ENV WHISPER_MODEL=tiny
ENV WHISPER_DEVICE=cpu
ENV WHISPER_COMPUTE_TYPE=int8

ENTRYPOINT ["/usr/bin/python3", "-m", "faster_whisper_mcp.server"]
