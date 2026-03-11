#!/bin/sh
set -e

python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn edaapp.wsgi --bind=0.0.0.0:${PORT:-8000}


# echo "Applying migrations..."
# python manage.py migrate --noinput

# echo "Collecting static files..."
# python manage.py collectstatic --noinput

# echo "Starting Gunicorn..."
# gunicorn edaapp.wsgi --bind=0.0.0.0:${PORT:-8000} --workers=${GUNICORN_WORKERS:-3} --timeout=${GUNICORN_TIMEOUT:-180}
