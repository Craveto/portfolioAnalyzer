#!/bin/sh
set -e

if [ ! -d "antenv" ]; then
  echo "Creating virtual environment..."
  python -m venv antenv
fi

. antenv/bin/activate

echo "Installing Python dependencies..."
python -m pip install --upgrade pip
if [ -f "requirements.azure.txt" ]; then
  python -m pip install -r requirements.azure.txt
else
  python -m pip install -r requirements.txt
fi

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
gunicorn edaapp.wsgi --bind=0.0.0.0:${PORT:-8000} --workers=${GUNICORN_WORKERS:-3} --timeout=${GUNICORN_TIMEOUT:-180}
