# Build stage on the Python the runtime ships: distroless python3-debian12 is CPython 3.11, so the
# compiled wheels (transcribe-cpp-native, av, numpy) match the interpreter that loads them.
FROM python:3.11-slim-bookworm AS build

WORKDIR /app
COPY pyproject.toml ./
COPY faster_whisper_mcp ./faster_whisper_mcp
# cryptography/cffi/pycparser arrive only through mcp -> pyjwt[crypto]; this stdio server signs nothing.
# pip/setuptools/wheel are packaging tools the runtime never imports.
RUN pip install --no-cache-dir --no-compile . \
 && pip uninstall -y cryptography cffi pycparser \
 && SP=/usr/local/lib/python3.11/site-packages \
 && rm -rf $SP/pip* $SP/setuptools* $SP/wheel* $SP/pkg_resources $SP/_distutils_hack $SP/distutils-precedence.pth \
 && find $SP -name __pycache__ -prune -exec rm -rf {} + \
 && find $SP -name '*.pyi' -delete

# Runtime: distroless python3 instead of python:3.12-slim — 53 MB vs 120 MB, and it drops the
# gcc/g++/dpkg-dev toolchain layer a runtime never uses. The console script is not copied; the
# package is run as a module (same main()). No model weights are baked in: the model GGUF (~740 MB)
# is fetched into the HF cache on first use, so the image stays small.
FROM gcr.io/distroless/python3-debian12@sha256:2fdb05402a2cf21cf78fdb3ba4c5db167241e9e498140f5bf689d7efb773731f

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/lib/python3/dist-packages
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

VOLUME ["/audio"]
ENTRYPOINT ["/usr/bin/python3", "-m", "faster_whisper_mcp.server"]
