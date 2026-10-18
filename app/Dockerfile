# Image unique de l'application v2 : extension Home Assistant ou Docker autonome
# (décision 1). Multi-architectures : linux/amd64, linux/arm64.
#
# Construction depuis la racine du repo :
#   docker build -t wattslot app

# --- Interface : compilée en fichiers statiques -------------------------------------------
FROM node:22.23.2-bookworm-slim AS frontend
WORKDIR /build
# npm 10 (livré avec Node 22) échoue sur les dépendances de Vitest : voir app/README.md.
RUN npm install -g npm@11.20.0
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- Application ---------------------------------------------------------------------------
FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WATTSLOT_DATA_DIR=/data \
    WATTSLOT_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/src backend/src
RUN pip install ./backend
COPY --from=frontend /build/dist /app/static

# /data : base SQLite et magasin Oxigraph. En extension, le Supervisor y monte le dossier de
# l'extension (inclus dans les sauvegardes de HA) ; en autonome, un volume Docker.
VOLUME /data
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/api/health', timeout=4)"
# Arrêt : 10 s au plus pour fermer les connexions ouvertes (flux MCP…), le reste du délai du
# Supervisor (30 s, config.yaml de l'extension) pour vider les écritures.
CMD ["uvicorn", "wattslot.main:app", "--host", "0.0.0.0", "--port", "8100",      "--timeout-graceful-shutdown", "10"]
