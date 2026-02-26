FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY bot/ bot/
RUN mkdir -p data
CMD ["python", "-m", "bot.main"]
