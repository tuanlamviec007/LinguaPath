#!/bin/sh
set -eu

python manage.py migrate --noinput

if [ "${AUTO_SEED:-true}" = "true" ]; then
  python manage.py seed_demo || true
  python manage.py seed_starter_content || true
fi

if [ "${DJANGO_DEBUG:-false}" = "true" ] || [ "${DJANGO_DEBUG:-false}" = "1" ]; then
  python manage.py check_release --local
else
  python manage.py check_release
fi

exec gunicorn config.wsgi:application \
  --logger-class config.observability.SafeGunicornLogger \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -

