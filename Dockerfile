# Agentic Tele-Triage Portal - Cloud Run image
#
# One container serves both the API and the static UI, so a judge needs a single
# URL. The UI is same-origin with the API, which means CORS never applies in the
# deployed configuration.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a source-only change does not re-resolve the world.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run runs as an unprivileged user; nothing here needs root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# `python main.py` reads $PORT (Cloud Run sets it to 8080 by default) and binds
# 0.0.0.0, which is what the platform requires.
CMD ["python", "main.py"]
