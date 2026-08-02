# Kung Fu Chess -- Event Consumer / DB Writer service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/event_consumer/requirements.txt ./services/event_consumer/requirements.txt
RUN pip install --no-cache-dir -r services/event_consumer/requirements.txt

# shared/, core/, engine/ -- the domain layers every service imports.
# The Event Consumer itself only needs shared/ (for schema constants);
# core/ and engine/ are copied for layout consistency with every other
# service's image.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/

COPY services/event_consumer/ ./services/event_consumer/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set via EVENT_CONSUMER_PORT (see
# docker-compose.yml / .env) -- 8030 here is only the image-level
# default/doc.
EXPOSE 8030

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('EVENT_CONSUMER_PORT', '8030') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.event_consumer.main:app --host 0.0.0.0 --port ${EVENT_CONSUMER_PORT:-8030}"]
