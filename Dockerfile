# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Ensure Python output is sent straight to terminal
    PYTHONFAULTHANDLER=1 \
    # pip configuration
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
# - gcc: required for some Python packages
# - libgl1, libgtk2.0-dev: required for opencv
# - postgresql-client: for pg_dump backups and psql access
# - libmagic1: for python-magic file type detection
# - curl: for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgl1 \
    libgtk2.0-dev \
    postgresql-client \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements first for better layer caching
# This layer is only rebuilt when requirements.txt changes
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# This layer is rebuilt when any source file changes
COPY . .

# Create scripts directory and ensure scripts are executable
RUN mkdir -p scripts \
    && chmod +x docker-entrypoint.sh \
    && chmod +x scripts/*.sh 2>/dev/null || true

# Create a non-root user for security
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose application port
EXPOSE 5000

# Healthcheck to ensure the application is responding
# Checks every 30 seconds, with 10 second timeout
# Fails after 3 consecutive failures
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/camposocial/api/ || exit 1

# Use entrypoint script for startup
# Note: Migrations should be run separately before deploying new code
ENTRYPOINT ["/bin/bash", "./docker-entrypoint.sh"]
