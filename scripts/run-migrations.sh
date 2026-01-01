#!/bin/bash
# ============================================================================
# CampoSocial Migration Runner Script
# ============================================================================
# This script safely runs database migrations with proper validation and
# error handling. It should be run BEFORE deploying new application code.
#
# Usage:
#   ./scripts/run-migrations.sh                    # Run all pending migrations
#   ./scripts/run-migrations.sh --dry-run          # Show what would be migrated
#   ./scripts/run-migrations.sh --downgrade 1      # Rollback last migration
#
# Environment:
#   DATABASE_URL      - PostgreSQL connection string (required)
#   FLASK_APP         - Flask application module (default: app.py)
#
# Exit codes:
#   0 - Success
#   1 - Pre-flight validation failed
#   2 - Migration failed
#   3 - Post-migration validation failed
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging helpers
log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

# Parse arguments
DRY_RUN=false
DOWNGRADE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --downgrade)
            DOWNGRADE="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================================================"
echo "  CampoSocial Database Migration Runner"
echo "============================================================================"
echo ""

# ============================================================================
# Step 1: Pre-flight validation
# ============================================================================
log_info "Running pre-flight validation..."

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    log_error "DATABASE_URL environment variable is not set"
    exit 1
fi
log_success "DATABASE_URL is configured"

# Check database connection
log_info "Testing database connection..."
python -c "
from app import create_app
from models import db
app, _ = create_app()
with app.app_context():
    db.engine.connect()
    print('Database connection successful')
" || {
    log_error "Failed to connect to database"
    exit 1
}
log_success "Database connection verified"

# ============================================================================
# Step 2: Check current migration status
# ============================================================================
log_info "Checking current migration status..."

CURRENT_VERSION=$(flask db current 2>&1 || echo "none")
log_info "Current migration version: ${CURRENT_VERSION:-none}"

HEAD_VERSION=$(flask db heads 2>&1 || echo "unknown")
log_info "Target migration version: ${HEAD_VERSION:-unknown}"

# ============================================================================
# Step 3: Dry run (if requested)
# ============================================================================
if [ "$DRY_RUN" = true ]; then
    log_info "DRY RUN MODE - showing pending migrations..."
    flask db show || log_warn "Could not show migration details"
    log_info "No changes made (dry run)"
    exit 0
fi

# ============================================================================
# Step 4: Run migrations or downgrade
# ============================================================================
if [ -n "$DOWNGRADE" ]; then
    log_warn "DOWNGRADE requested: rolling back $DOWNGRADE migration(s)"
    echo ""
    read -p "Are you sure you want to downgrade? This may cause data loss. (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Downgrade cancelled"
        exit 0
    fi
    
    log_info "Rolling back migrations..."
    flask db downgrade "-${DOWNGRADE}" || {
        log_error "Downgrade failed"
        exit 2
    }
    log_success "Downgrade completed"
else
    log_info "Running pending migrations..."
    flask db upgrade || {
        log_error "Migration failed!"
        log_error "The database may be in an inconsistent state."
        log_error "Check the error above and consider rolling back."
        exit 2
    }
    log_success "Migrations completed successfully"
fi

# ============================================================================
# Step 5: Post-migration validation
# ============================================================================
log_info "Running post-migration validation..."

# Check new version
NEW_VERSION=$(flask db current 2>&1 || echo "unknown")
log_info "New migration version: ${NEW_VERSION:-unknown}"

# Verify database is accessible
python -c "
from app import create_app
from models import db, Users
app, _ = create_app()
with app.app_context():
    # Simple query to verify tables exist and are accessible
    count = db.session.query(db.func.count(Users.id)).scalar()
    print(f'Users table accessible, {count} records')
" || {
    log_error "Post-migration validation failed!"
    log_error "Database may be in an inconsistent state."
    exit 3
}

log_success "Post-migration validation passed"

echo ""
echo "============================================================================"
log_success "Migration completed successfully!"
echo "============================================================================"

