# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libgl1 \
    libgtk2.0-dev \
    postgresql-client \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a non-root user to run the app
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port 5000
EXPOSE 5000

# Run the application with gunicorn using eventlet worker for Socket.IO
# Using eventlet worker class for proper WebSocket support
# --workers 1: eventlet handles concurrency via green threads
# --worker-connections: max simultaneous clients per worker
# --timeout: worker timeout (longer for WebSocket connections)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--worker-class", "eventlet", \
     "--workers", "1", \
     "--worker-connections", "1000", \
     "--timeout", "300", \
     "--keep-alive", "65", \
     "--log-level", "info", \
     "wsgi:app"]
