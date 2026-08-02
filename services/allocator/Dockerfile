# Kung Fu Chess -- Game Allocator service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/allocator/requirements.txt ./services/allocator/requirements.txt
RUN pip install --no-cache-dir -r services/allocator/requirements.txt

# shared/, core/, engine/ -- the domain layers every service imports.
# The Allocator itself is pure Redis compute (decision 10) and doesn't
# actually reach into engine/, but these are copied for layout
# consistency with every other service's image.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/

COPY services/allocator/ ./services/allocator/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set via ALLOCATOR_PORT (see
# docker-compose.yml / .env) -- 8020 here is only the image-level
# default/doc.
EXPOSE 8020

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('ALLOCATOR_PORT', '8020') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.allocator.main:app --host 0.0.0.0 --port ${ALLOCATOR_PORT:-8020}"]
