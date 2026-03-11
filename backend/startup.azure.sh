#!/bin/sh
set -e

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
gunicorn edaapp.wsgi --bind=0.0.0.0:${PORT:-8000} --workers=${GUNICORN_WORKERS:-3} --timeout=${GUNICORN_TIMEOUT:-180}
