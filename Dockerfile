# Tofu (2026-10-25): this file is Tofu's addition; it is not part of upstream linkding.
#
# The image Tofu builds and runs for a copy of linkding (framework preset `container`, see TOFU.md). It follows the
# `linkding` target of upstream's docker/default.Dockerfile: a Node stage builds the scripts and styles, a Python stage
# installs the locked dependencies (with PostgreSQL's driver built against libpq, and uwsgi), and the final image
# collects the static files. Left out: the SQLite ICU extension (a copy keeps its data in PostgreSQL), the health check
# (Tofu checks the address itself), uv's install script (uv comes from PyPI, pinned) and the "plus" image's Chromium.
# Its settings are bookmarks/settings/tofu.py (upstream's production settings, then Tofu's). tofu-entrypoint.sh applies
# the migrations, then starts the web server and the background tasks; the container runs as root (no USER line). uwsgi's
# master starts as root and, with UWSGI_DROP_AFTER_INIT below, binds PORT before it drops to www-data (upstream's
# uwsgi.ini), so linkding itself, uwsgi's workers and its HTTP router run as www-data, and so do the background tasks.
FROM node:22-alpine AS node-build
WORKDIR /etc/linkding
COPY package.json package-lock.json ./
RUN npm ci
COPY bookmarks/frontend ./bookmarks/frontend
COPY bookmarks/styles ./bookmarks/styles
RUN npm run build


FROM python:3.13.7-slim-trixie AS build-deps
# build-essential pkg-config: build Python packages from source
# libpq-dev: build the PostgreSQL driver (psycopg's C implementation)
# libffi-dev libpcre2-dev: build uwsgi, with its internal routing
RUN apt-get update && apt-get -y install build-essential pkg-config libpq-dev libffi-dev libpcre2-dev
WORKDIR /etc/linkding
ENV PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN pip install uv==0.8.13
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group postgres


FROM python:3.13.7-slim-trixie
RUN apt-get update && apt-get -y install media-types libpq-dev libssl3t64 libpcre2-8-0 && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /etc/linkding
COPY --from=build-deps /etc/linkding/.venv /etc/linkding/.venv
COPY --from=node-build /etc/linkding/bookmarks/static bookmarks/static/
COPY . .
ENV VIRTUAL_ENV=/etc/linkding/.venv \
    PATH="/etc/linkding/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=bookmarks.settings.tofu \
    UWSGI_MAX_FD=4096
# uwsgi reads UWSGI_* variables as options. Without drop-after-init its master drops to www-data (uwsgi.ini's uid and
# gid) before its HTTP router binds PORT, and www-data cannot bind port 80, Tofu's default: uwsgi would exit and nothing
# would answer. With it, the master binds PORT and its internal socket as root, then drops to www-data before it loads
# linkding.
ENV UWSGI_DROP_AFTER_INIT=true
# Upstream's .dockerignore already leaves out the development settings; removing them here too makes sure that
# bookmarks.settings can never fall back to them (DEBUG on).
RUN rm -f bookmarks/settings/dev.py && \
    mkdir -p data && \
    python manage.py collectstatic --noinput

EXPOSE 80
CMD ["/bin/sh", "/etc/linkding/tofu-entrypoint.sh"]
