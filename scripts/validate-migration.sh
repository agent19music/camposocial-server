#!/bin/bash
# ============================================================================
# CampoSocial Pre-Deployment Validation Script
# ============================================================================
# This script validates the environment before running migrations or deploying.
# Run this script to ensure everything is properly configured.
#
# Usage:
#   ./scripts/validate-migration.sh
#
# Checks performed:
#   1. Environment variables are set
#   2. Database is accessible
#   3. Migration files are in sync
#   4. No pending uncommitted migrations
#
# Exit codes:
#   0 - All validations passed
#   1 - Validation failed
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNED=0

# Logging helpers
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((CHECKS_PASSED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((CHECKS_WARNED++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((CHECKS_FAILED++))
}

echo "============================================================================"
echo "  CampoSocial Pre-Deployment Validation"
echo "============================================================================"
echo ""

# ============================================================================
# Check 1: Required environment variables
# ============================================================================
log_info "Checking required environment variables..."

check_env_var() {
    if [ -z "${!1}" ]; then
        log_error "$1 is not set"
        return 1
    else
        log_success "$1 is configured"
        return 0
    fi
}

check_env_var "DATABASE_URL" || true
check_env_var "SECRET_KEY" || true
check_env_var "JWT_SECRET_KEY" || true

# Optional but recommended
if [ -z "$REDIS_HOST" ]; then
    log_warn "REDIS_HOST is not set (using default)"
fi

echo ""

# ============================================================================
# Check 2: Database connectivity
# ============================================================================
log_info "Testing database connection..."

if python -c "
from app import create_app
from models import db
app, _ = create_app()
with app.app_context():
    connection = db.engine.connect()
    connection.close()
" 2>/dev/null; then
    log_success "Database connection successful"
else
    log_error "Cannot connect to database"
fi

echo ""

# ============================================================================
# Check 3: Migration status
# ============================================================================
log_info "Checking migration status..."

# Get current and head versions
CURRENT=$(flask db current 2>/dev/null | grep -v "^INFO" | head -1 || echo "")
HEAD=$(flask db heads 2>/dev/null | grep -v "^INFO" | head -1 || echo "")

if [ -z "$CURRENT" ]; then
    log_warn "No migrations have been applied to this database"
    log_info "Run 'flask db upgrade' to apply migrations"
elif [ "$CURRENT" = "$HEAD" ] || [ -z "$HEAD" ]; then
    log_success "Database is up to date (${CURRENT})"
else
    log_warn "Pending migrations detected"
    log_info "Current: $CURRENT"
    log_info "Target:  $HEAD"
fi

echo ""

# ============================================================================
# Check 4: Migration files exist
# ============================================================================
log_info "Checking migration files..."

if [ -d "migrations/versions" ]; then
    MIGRATION_COUNT=$(find migrations/versions -name "*.py" ! -name "__*" 2>/dev/null | wc -l)
    if [ "$MIGRATION_COUNT" -gt 0 ]; then
        log_success "Found $MIGRATION_COUNT migration file(s)"
    else
        log_warn "No migration files found in migrations/versions/"
        log_info "Run 'flask db init' and 'flask db migrate' to create migrations"
    fi
else
    log_error "migrations/versions/ directory not found"
    log_info "Run 'flask db init' to initialize migrations"
fi

echo ""

# ============================================================================
# Check 5: Flask app loads correctly
# ============================================================================
log_info "Verifying Flask application loads..."

if python -c "
from app import create_app
app, socketio = create_app()
print(f'Flask app created successfully')
print(f'Registered blueprints: {len(app.blueprints)}')
" 2>/dev/null; then
    log_success "Flask application loads correctly"
else
    log_error "Flask application failed to load"
fi

echo ""

# ============================================================================
# Check 6: Redis connectivity (if configured)
# ============================================================================
if [ -n "$REDIS_HOST" ] || [ -n "$REDIS_URL" ]; then
    log_info "Testing Redis connection..."
    
    if python -c "
from redis_config import get_redis_client, test_redis_connection
success, message = test_redis_connection()
if success:
    print('Redis connection successful')
else:
    raise Exception(message)
" 2>/dev/null; then
        log_success "Redis connection successful"
    else
        log_warn "Cannot connect to Redis (WebSocket features may not work)"
    fi
    echo ""
fi

# ============================================================================
# Summary
# ============================================================================
echo "============================================================================"
echo "  Validation Summary"
echo "============================================================================"
echo -e "  ${GREEN}Passed:${NC}  $CHECKS_PASSED"
echo -e "  ${YELLOW}Warnings:${NC} $CHECKS_WARNED"
echo -e "  ${RED}Failed:${NC}  $CHECKS_FAILED"
echo "============================================================================"

if [ $CHECKS_FAILED -gt 0 ]; then
    echo ""
    log_error "Validation FAILED - please fix the issues above before deploying"
    exit 1
elif [ $CHECKS_WARNED -gt 0 ]; then
    echo ""
    log_warn "Validation passed with warnings - review before deploying"
    exit 0
else
    echo ""
    log_success "All validations passed - ready to deploy!"
    exit 0
fi

