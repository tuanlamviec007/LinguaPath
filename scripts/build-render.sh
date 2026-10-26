#!/bin/sh
# Reviewed release preparation for Render Free (no pre-deploy jobs/shell).
set -eu

python -c "import platform,sys; assert sys.version_info[:2] == (3,12) and platform.machine() in ('x86_64','AMD64'), 'requirements.lock requires Python 3.12 Linux x86_64'"
python -m pip install --require-hashes -r requirements.lock
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py bootstrap_learning_content --if-empty
python manage.py check_release
