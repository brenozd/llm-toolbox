FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY woodpecker_mcp ./woodpecker_mcp
RUN pip install --no-cache-dir .

VOLUME ["/config"]
ENV WOODPECKER_MCP_CONFIG=/config/config.json

ENTRYPOINT ["woodpecker-mcp"]
