# Not distroless: the runtime shells out to the tesseract binary, which needs its apt libraries.
# tessdata is the Debian "fast" model; osd is installed for orientation detection.
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por tesseract-ocr-eng tesseract-ocr-osd \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY document_ocr_mcp ./document_ocr_mcp
RUN pip install --no-cache-dir --no-compile . \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ocr

USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DOCUMENT_OCR_ROOTS=/data
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "document_ocr_mcp.server"]
