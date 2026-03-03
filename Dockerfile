FROM python:3.12-slim

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Install Playwright browsers
RUN playwright install chromium

# Copy application
COPY core/ core/
COPY api/ api/
COPY bot/ bot/
COPY web/ web/
RUN mkdir -p data

EXPOSE 8080

# Default: run the web app + API
# Override with: CMD ["python", "-m", "bot.main"] for Telegram-only
CMD ["python", "-m", "api.main"]
