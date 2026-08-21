FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY faster_whisper_mcp ./faster_whisper_mcp
RUN pip install --no-cache-dir .

VOLUME ["/audio"]
ENV WHISPER_MODEL=tiny
ENV WHISPER_DEVICE=cpu
ENV WHISPER_COMPUTE_TYPE=int8

ENTRYPOINT ["faster-whisper-mcp"]
