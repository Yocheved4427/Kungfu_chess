# Kung Fu Chess -- Reaper service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/reaper/requirements.txt ./services/reaper/requirements.txt
RUN pip install --no-cache-dir -r services/reaper/requirements.txt

# shared/, core/, engine/ -- the domain layers every service imports.
# The Reaper itself is pure Redis/Kafka compute (no game logic at all)
# and doesn't actually reach into engine/, but these are copied for
# layout consistency with every other service's image.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/

COPY services/reaper/ ./services/reaper/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set via REAPER_PORT (see docker-compose.yml
# / .env) -- 8040 here is only the image-level default/doc.
EXPOSE 8040

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('REAPER_PORT', '8040') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.reaper.main:app --host 0.0.0.0 --port ${REAPER_PORT:-8040}"]
