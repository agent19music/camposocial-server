#!/bin/bash
set -e

# ============================================================================
# CampoSocial Server Entrypoint Script
# ============================================================================
# This script handles:
# - Migration-only mode (MIGRATE_ONLY=true)
# - Optional badge seeding (SEED_BADGES=true)
# - Graceful shutdown handling
# - Application startup with Gunicorn
#
# IMPORTANT: Migrations should be run SEPARATELY before deploying new code.
# Use MIGRATE_ONLY=true to run migrations without starting the server.
# ============================================================================

# Logging helper with timestamps
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Starting CampoSocial Server..."

# Graceful shutdown handler
shutdown_handler() {
    log "Received shutdown signal, gracefully stopping..."
    if [ -n "$GUNICORN_PID" ]; then
        kill -TERM "$GUNICORN_PID" 2>/dev/null || true
        wait "$GUNICORN_PID" 2>/dev/null || true
    fi
    log "Shutdown complete"
    exit 0
}

# Set up signal traps for graceful shutdown
trap shutdown_handler SIGTERM SIGINT SIGQUIT

# ============================================================================
# Migration-only mode
# ============================================================================
# When MIGRATE_ONLY=true, run migrations and exit
# This is used for running migrations before deploying new code
if [ "${MIGRATE_ONLY:-false}" = "true" ]; then
    log "Running in MIGRATION-ONLY mode..."
    
    log "Checking database connection..."
    python -c "from app import create_app; from models import db; app, _ = create_app(); app.app_context().push(); db.engine.connect(); print('Database connection successful')" || {
        log "ERROR: Failed to connect to database"
        exit 1
    }
    
    log "Running database migrations..."
    flask db upgrade || {
        log "ERROR: Migration failed"
        exit 1
    }
    
    log "Checking migration status..."
    flask db current || true
    
    log "Migrations completed successfully"
    exit 0
fi

# ============================================================================
# Optional: Seed badges (including university badges)
# ============================================================================
if [ "${SEED_BADGES:-false}" = "true" ]; then
    log "Seeding default badges..."
    python seed_badges.py || log "WARNING: Default badge seeding failed (may already exist)"

    log "Seeding university badges..."
    python seed_university_badges.py || log "WARNING: University badge seeding failed (may already exist)"
fi

# ============================================================================
# Start the application server
# ============================================================================
# Run migrations automatically (Smooth no manual mode)
log "Running automatic database migrations..."
flask db upgrade || log "WARNING: Automatic migration failed, proceeding anyway..."


log "Starting Gunicorn with eventlet worker..."
log "Server will be available on port 5000"

# Start Gunicorn in background to capture PID for graceful shutdown
exec gunicorn --bind 0.0.0.0:5000 \
     --worker-class eventlet \
     --workers 1 \
     --worker-connections 1000 \
     --timeout 300 \
     --keep-alive 65 \
     --log-level info \
     --access-logfile - \
     --error-logfile - \
     --capture-output \
     --enable-stdio-inheritance \
     wsgi:application &

GUNICORN_PID=$!
log "Gunicorn started with PID $GUNICORN_PID"

# Wait for Gunicorn to exit
wait $GUNICORN_PID
