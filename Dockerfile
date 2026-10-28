# Keep application rollouts on the base verified by the working ALU image.
# A floating tag changed Debian layers during the 28 October rollout.
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.13-slim-bookworm@sha256:93498f36dc7e24ef233bfdf6cc17d4b8bd32d94ee737143e906460d5f5a914c5

# python-ldap is imported by this fork even when ALU is the only login.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libldap2-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=settings_cloudflare
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN useradd --create-home helios
COPY --chown=helios:helios . .
RUN install -d -o helios -g helios /app/media
USER helios
CMD ["sh", "scripts/backend-start.sh"]
