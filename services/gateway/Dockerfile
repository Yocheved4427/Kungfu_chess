# Kung Fu Chess -- Gateway / Auth service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`), not this directory -- that's what lets this
# Dockerfile reach shared/, core/, engine/, and server/ alongside its
# own services/gateway/ folder.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install this service's own dependencies first -- this layer only
# rebuilds when services/gateway/requirements.txt itself changes, not on
# every application code edit.
COPY services/gateway/requirements.txt ./services/gateway/requirements.txt
RUN pip install --no-cache-dir -r services/gateway/requirements.txt

# The domain layers every Kung Fu Chess service imports and none of them
# own (Server_Design.md, Part B) -- unchanged, framework-free Python.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/

# This service's own code.
COPY services/gateway/ ./services/gateway/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set via GATEWAY_PORT (see docker-compose.yml
# / .env) -- 8000 here is only the image-level default/doc.
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('GATEWAY_PORT', '8000') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.gateway.main:app --host 0.0.0.0 --port ${GATEWAY_PORT:-8000}"]
