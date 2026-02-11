#!/bin/bash
set -e

echo "=== CampoSocial Staging Startup ==="
echo "=== DATABASE_URL prefix: ${DATABASE_URL:0:30}... ==="

echo "=== Running flask db upgrade ==="
export FLASK_APP=app.py
flask db upgrade 2>&1
echo "=== Migrations complete ==="

echo "=== Starting Gunicorn ==="
exec gunicorn --worker-class eventlet --bind 0.0.0.0:${PORT:-5000} wsgi:application
