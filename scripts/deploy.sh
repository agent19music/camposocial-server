#!/bin/bash
# ============================================================================
# CampoSocial Deployment Script
# ============================================================================
# Usage:
#   ./scripts/deploy.sh                  # Full deployment with migrations
#   ./scripts/deploy.sh --code-only      # Skip migrations (code changes only)
#   ./scripts/deploy.sh --help           # Show help
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $(date '+%H:%M:%S') $1"; }
success() { echo -e "${GREEN}[OK]${NC} $(date '+%H:%M:%S') $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $(date '+%H:%M:%S') $1"; }
error() { echo -e "${RED}[ERROR]${NC} $(date '+%H:%M:%S') $1"; }

CODE_ONLY=false

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --code-only)
            CODE_ONLY=true
            shift
            ;;
        --help)
            echo "Usage: ./scripts/deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --code-only    Skip migration service (for code-only changes)"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "  CampoSocial Deployment"
echo "============================================"
echo ""

# Check for .env.prod
if [ ! -f ".env.prod" ]; then
    error ".env.prod file not found!"
    exit 1
fi

# Pull latest code
log "Pulling latest code..."
git pull || warn "Git pull failed (continuing anyway)"

# Build image
log "Building Docker image..."
docker build -t camposocial-server:latest .
success "Image built"

# Deploy
if [ "$CODE_ONLY" = true ]; then
    warn "CODE-ONLY mode: Skipping migrations"
    log "Restarting app container..."
    docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --no-deps app
else
    log "Full deployment with migrations..."
    docker compose -f docker-compose.prod.yml --env-file .env.prod down
    docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
fi

# Wait for health
log "Waiting for health check..."
sleep 10

# Verify
if curl -sf http://localhost:5000/camposocial/api/ > /dev/null; then
    success "App is healthy!"
else
    error "Health check failed!"
    docker compose -f docker-compose.prod.yml logs app --tail 50
    exit 1
fi

echo ""
echo "============================================"
success "Deployment complete!"
echo "============================================"
