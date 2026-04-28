FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium — installed only if needed at runtime
# Run: docker compose run --rm factures2tiime playwright install chromium --with-deps
# Or set INSTALL_PLAYWRIGHT=true to install at build time (larger image)
ARG INSTALL_PLAYWRIGHT=false
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
            libx11-6 libxcomposite1 libxdamage1 libxrandr2 \
            libgbm1 libasound2 fonts-liberation && \
        rm -rf /var/lib/apt/lists/* && \
        playwright install chromium; \
    fi

COPY . .

RUN mkdir -p /app/data/pdfs

RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --home-dir /app appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
