FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/scripts ./scripts
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.8 AS uv
FROM caddy:2-alpine AS caddy
FROM axllent/mailpit:v1.33.0 AS mailpit
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY --from=mailpit /mailpit /usr/local/bin/mailpit
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY deploy/Caddyfile /app/deploy/Caddyfile
COPY deploy/render-entrypoint.py /app/deploy/render-entrypoint.py
COPY --from=frontend /build/dist /srv
RUN SITE_ADDRESS=:10000 API_UPSTREAM=127.0.0.1:8000 MAILPIT_UPSTREAM=127.0.0.1:8025 \
    caddy validate --config /app/deploy/Caddyfile --adapter caddyfile
RUN groupadd --gid 10001 talent && useradd --uid 10001 --gid talent --no-create-home talent \
    && mkdir -p /app/var/uploads /app/var/mail /app/var/caddy /app/var/home \
    && chown -R talent:talent /app/var
ENV HOME=/app/var/home XDG_CONFIG_HOME=/app/var/caddy XDG_DATA_HOME=/app/var/caddy
USER talent
EXPOSE 10000
CMD ["python", "/app/deploy/render-entrypoint.py"]
