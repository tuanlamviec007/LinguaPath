FROM python:3.12-slim AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
COPY requirements.txt requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -c "import platform,sys; assert sys.version_info[:2] == (3,12) and platform.machine() in ('x86_64','AMD64'), 'requirements.lock targets Python 3.12 Linux x86_64'" \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim AS app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=false

WORKDIR /app
RUN groupadd --system --gid 10001 lingua \
    && useradd --system --uid 10001 --gid lingua --home-dir /app --no-create-home lingua

COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=lingua:lingua config/ /app/config/
COPY --chown=lingua:lingua learning/ /app/learning/
COPY --chown=lingua:lingua planner/ /app/planner/
COPY --chown=lingua:lingua templates/ /app/templates/
COPY --chown=lingua:lingua static/ /app/static/
COPY --chown=lingua:lingua scripts/ /app/scripts/
COPY --chown=lingua:lingua manage.py requirements.txt requirements.lock /app/

# collectstatic imports settings but does not access the database. These
# build-only values are placeholders and are not persisted as runtime ENV.
RUN mkdir -p /app/staticfiles \
    && chown lingua:lingua /app/staticfiles \
    && chmod +x /app/scripts/*.sh \
    && DJANGO_SECRET_KEY='build-only-placeholder-secret-key-not-for-runtime-0123456789' \
       DATABASE_URL='postgresql://build:build@127.0.0.1:5432/build' \
       python manage.py collectstatic --noinput

USER lingua:lingua
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/scripts/start-production.sh"]

