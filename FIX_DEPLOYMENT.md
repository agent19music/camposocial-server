# Fix for Fly.io 503 Error - CampoSocial Server

## Issue Identified
Your app is returning a 503 error because:
1. ✅ **FIXED**: Port mismatch (fly.toml was expecting port 8080, but your app runs on 5000)
2. **PENDING**: Missing environment variables on Fly.io

## Required Environment Variables

Based on your application code, you need to set these environment variables on Fly.io:

### Critical Variables (App won't start without these):
```bash
DATABASE_URL          # PostgreSQL connection string
SECRET_KEY           # Flask secret key
JWT_SECRET_KEY       # JWT authentication key
FRONTEND_URL         # Your frontend URL (for CORS)
```

### Optional but Important Variables:
```bash
# R2/S3 Storage (for file uploads)
R2_ENDPOINT_URL
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
IMAGE_PREFIX

# OAuth (if using social login)
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET

# Redis (if using Redis features)
REDIS_HOST
REDIS_PORT
REDIS_DB

# Payment (if using payments)
PAYSTACK_SECRET_KEY
```

## Step-by-Step Fix

### 1. Install Fly CLI (if not already installed)
```bash
# On Linux/Mac:
curl -L https://fly.io/install.sh | sh

# On Arch Linux (using yay):
yay -S flyctl-bin
```

### 2. Set Environment Variables on Fly.io

First, check your current secrets:
```bash
fly secrets list
```

Then set the required variables:

```bash
# Set database URL (Fly.io provides PostgreSQL)
fly postgres create --name camposocial-db
fly postgres attach --app camposocial-server camposocial-db

# This will automatically set DATABASE_URL

# Set other critical secrets
fly secrets set SECRET_KEY="your-very-secure-secret-key-here"
fly secrets set JWT_SECRET_KEY="your-jwt-secret-key-here"
fly secrets set FRONTEND_URL="https://your-frontend-domain.com"

# If using R2/S3 for file storage:
fly secrets set R2_ENDPOINT_URL="https://your-account-id.r2.cloudflarestorage.com"
fly secrets set R2_ACCESS_KEY_ID="your-r2-access-key"
fly secrets set R2_SECRET_ACCESS_KEY="your-r2-secret-key"
fly secrets set R2_BUCKET_NAME="your-bucket-name"
fly secrets set IMAGE_PREFIX="https://your-r2-public-url.com/"

# If using OAuth:
fly secrets set GOOGLE_CLIENT_ID="your-google-client-id"
fly secrets set GOOGLE_CLIENT_SECRET="your-google-client-secret"
fly secrets set GITHUB_CLIENT_ID="your-github-client-id"
fly secrets set GITHUB_CLIENT_SECRET="your-github-client-secret"

# If using Redis:
fly redis create --name camposocial-redis
# This will give you connection details, then:
fly secrets set REDIS_HOST="your-redis-host"
fly secrets set REDIS_PORT="6379"
fly secrets set REDIS_DB="0"
```

### 3. Deploy with Updated Configuration

```bash
# Deploy your application
fly deploy

# Check deployment status
fly status

# Check logs for any errors
fly logs
```

### 4. Debug if Still Having Issues

```bash
# SSH into your container to debug
fly ssh console

# Check if your app is running
ps aux

# Test the app locally in the container
curl http://localhost:5000/camposocial/api/

# Check environment variables
env | grep -E "DATABASE_URL|SECRET_KEY|JWT_SECRET_KEY|FRONTEND_URL"
```

### 5. Monitor Your App

```bash
# Watch real-time logs
fly logs --tail

# Check app metrics
fly dashboard
```

## Quick Fix Script

Save this as `deploy-fix.sh` and run it:

```bash
#!/bin/bash

echo "Fixing CampoSocial Server Deployment..."

# Check if fly CLI is installed
if ! command -v fly &> /dev/null; then
    echo "Fly CLI not found. Installing..."
    curl -L https://fly.io/install.sh | sh
fi

# Deploy with updated configuration
echo "Deploying with fixed port configuration..."
fly deploy

# Check status
echo "Checking deployment status..."
fly status

# Show logs
echo "Showing recent logs..."
fly logs --limit 50

echo "Deployment fix complete! Check https://camposocial-server.fly.dev/"
```

## Verification

After deployment, test these endpoints:

1. **Root endpoint**: https://camposocial-server.fly.dev/
2. **API endpoint**: https://camposocial-server.fly.dev/camposocial/api/
3. **API Explorer**: https://camposocial-server.fly.dev/api-explorer
4. **Docs**: https://camposocial-server.fly.dev/docs

## Common Issues and Solutions

### Issue: Still getting 503 after port fix
**Solution**: Check if DATABASE_URL is set. The app needs a database to start.

### Issue: Database migration errors
**Solution**: SSH into container and run migrations manually:
```bash
fly ssh console
cd /app
python -m flask db upgrade
```

### Issue: Static files not loading
**Solution**: Ensure your Dockerfile copies all necessary files and that .dockerignore isn't excluding needed files.

## Emergency Rollback

If something goes wrong:
```bash
# List all releases
fly releases

# Rollback to previous version
fly deploy --image registry.fly.io/camposocial-server:deployment-<previous-version-id>
```

## Support

For more help:
- Fly.io Status: https://status.fly.io/
- Fly.io Community: https://community.fly.io/
- Documentation: https://fly.io/docs/
