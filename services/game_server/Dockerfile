# Kung Fu Chess -- Game Server service
# Build context is the REPO ROOT (see docker-compose.yml's
# `build.context: .`). This single image is reused for every Game
# Server replica (game_server_1, game_server_2, ...) in
# docker-compose.yml -- each container gets its own GAME_SERVER_ID/
# GAME_SERVER_PORT via environment variables, not a separate image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/game_server/requirements.txt ./services/game_server/requirements.txt
RUN pip install --no-cache-dir -r services/game_server/requirements.txt

# shared/, core/, engine/ -- the domain layers every service imports.
COPY shared/ ./shared/
COPY core/ ./core/
COPY engine/ ./engine/
# engine.game.GameEngine itself imports controllers/, realtime/, input/,
# and ui.bus/ui.events at module load time -- all four are required for
# `import engine.game` to succeed, not optional extras.
COPY controllers/ ./controllers/
COPY realtime/ ./realtime/
COPY input/ ./input/
COPY ui/ ./ui/
# server/game/real_time_arbiter.py + server/game/rules/* -- the
# real-time orchestration and legality facade this service hosts
# UNCHANGED (Server_Design.md decision 7: no rewrite).
COPY server/ ./server/

COPY services/game_server/ ./services/game_server/

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Actual published port is set per-container via GAME_SERVER_PORT (see
# docker-compose.yml) -- 8001 here is only the image-level default/doc.
EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('GAME_SERVER_PORT', '8001') + '/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn services.game_server.main:app --host 0.0.0.0 --port ${GAME_SERVER_PORT:-8001}"]
