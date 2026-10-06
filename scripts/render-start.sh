#!/bin/sh
set -eu
# Free services have no pre-deploy command. Migrate on each demo startup.
python manage.py check
python manage.py migrate --noinput
exec gunicorn wsgi:application --bind "0.0.0.0:${PORT:-10000}" \
  --workers 1 --threads 1 --timeout 180 --error-logfile -
