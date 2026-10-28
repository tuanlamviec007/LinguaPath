#!/bin/sh
set -eu

python manage.py check_release

exec gunicorn config.wsgi:application \
  --logger-class config.observability.SafeGunicornLogger \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --worker-class gthread --threads "${GUNICORN_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -
