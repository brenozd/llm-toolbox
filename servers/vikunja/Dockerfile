FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY vikunja_mcp ./vikunja_mcp
RUN pip install --no-cache-dir .

VOLUME ["/config"]
ENV VIKUNJA_MCP_CONFIG=/config/config.json

ENTRYPOINT ["vikunja-mcp"]
