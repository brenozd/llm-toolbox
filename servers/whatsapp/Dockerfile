# One stage: the WhatsApp Web protocol runs in-process. neonize ships prebuilt manylinux
# wheels (x86_64 + aarch64) with the whatsmeow Go core, loaded via ctypes, so there is
# nothing to compile and pip resolves the wheel for TARGETARCH.
FROM python:3.12-slim

# ffmpeg: voice-note encoding to Opus/Ogg. libmagic1: imported by neonize (python-magic)
# at import time. neonize's own .so links against libc only (checked with ldd).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 wa \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin wa \
    && install -d -o 10001 -g 10001 -m 0700 /data \
    && install -d -m 0755 /media

WORKDIR /app
COPY pyproject.toml ./
COPY whatsapp_mcp ./whatsapp_mcp
RUN pip install --no-cache-dir .

USER 10001:10001
VOLUME ["/data"]
ENV WHATSAPP_MCP_CONFIG=/config/config.json

ENTRYPOINT ["whatsapp-mcp"]
