FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY actual_budget_mcp ./actual_budget_mcp
RUN pip install --no-cache-dir .

VOLUME ["/config", "/data"]
ENV ACTUAL_MCP_CONFIG=/config/config.json

ENTRYPOINT ["actual-budget-mcp"]
