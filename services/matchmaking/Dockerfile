# Kung Fu Chess -- Matchmaking service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/matchmaking/requirements.txt ./services/matchmaking/requirements.txt
RUN pip install --no-cache-dir -r services/matchmaking/requirements.txt

# shared/, core/, engine/ -- the domain layers every service imports.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/
# server/services/matchmaking_service.py -- this service reuses its
# ELO-window pairing algorithm UNCHANGED (see services/matchmaking/main.py).
COPY server/ ./server/

COPY services/matchmaking/ ./services/matchmaking/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set via MATCHMAKING_PORT (see
# docker-compose.yml / .env) -- 8010 here is only the image-level
# default/doc.
EXPOSE 8010

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('MATCHMAKING_PORT', '8010') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.matchmaking.main:app --host 0.0.0.0 --port ${MATCHMAKING_PORT:-8010}"]
