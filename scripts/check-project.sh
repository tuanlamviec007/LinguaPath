#!/bin/sh
# Read-only source checks; Django tests use their own isolated test database.
set -eu

project_python="${PYTHON:-python}"
case "${1:-}" in
  '') ;;
  --require-postgresql)
    "$project_python" -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); import django; django.setup(); from django.db import connection; import sys; sys.exit(0 if connection.vendor == "postgresql" else "PostgreSQL is required for this check run; refusing a SQLite fallback.")'
    ;;
  *) echo 'Usage: check-project.sh [--require-postgresql]' >&2; exit 2 ;;
esac
"$project_python" manage.py check
"$project_python" manage.py makemigrations --check --dry-run
"$project_python" manage.py test --noinput
node --test scripts/test_*.cjs
