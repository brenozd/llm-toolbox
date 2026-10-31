# Build stage on the Python the runtime ships: distroless python3-debian12 is CPython 3.11, so
# wheels compiled here (pydantic_core, cryptography) match the interpreter that loads them.
FROM python:3.11-slim-bookworm AS build

WORKDIR /app
COPY pyproject.toml ./
COPY woodpecker_mcp ./woodpecker_mcp
RUN pip install --no-cache-dir --no-compile --prefix=/install . \
 && rm -rf /install/lib/python3.11/site-packages/cryptography* /install/lib/python3.11/site-packages/cffi* /install/lib/python3.11/site-packages/_cffi_backend* /install/lib/python3.11/site-packages/pycparser* \
 && find /install -name __pycache__ -prune -exec rm -rf {} + \
 && find /install -name '*.pyi' -delete

# Runtime: distroless python3 instead of python:3.12-slim — 53 MB vs 120 MB, and it drops the
# gcc/g++/dpkg-dev toolchain layer a runtime never uses. The console script is not copied; the
# package is run as a module (same main()).
FROM gcr.io/distroless/python3-debian12@sha256:2fdb05402a2cf21cf78fdb3ba4c5db167241e9e498140f5bf689d7efb773731f

COPY --from=build /install/lib/python3.11/site-packages /usr/lib/python3/dist-packages
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

VOLUME ["/config"]
ENV WOODPECKER_MCP_CONFIG=/config/config.json

ENTRYPOINT ["/usr/bin/python3", "-m", "woodpecker_mcp.server"]
