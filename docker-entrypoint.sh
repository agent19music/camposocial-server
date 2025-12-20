#!/bin/bash
set -e

echo "🚀 Starting CampoSocial Server..."

# Run migrations
echo "📦 Running database migrations..."
flask db upgrade || echo "⚠️ Migrations skipped or already applied"

# Seed badges if SEED_BADGES env is set
if [ "${SEED_BADGES:-false}" = "true" ]; then
    echo "🏆 Seeding badges..."
    python seed_badges.py || echo "⚠️ Badge seeding failed"
fi

# Start the server
echo "🌐 Starting Gunicorn with eventlet..."
exec gunicorn --bind 0.0.0.0:5000 \
     --worker-class eventlet \
     --workers 1 \
     --worker-connections 1000 \
     --timeout 300 \
     --keep-alive 65 \
     --log-level info \
     wsgi:application
