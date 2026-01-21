# CampoSocial Server Deployment Guide

Complete guide for deploying the CampoSocial server to DigitalOcean.

## Prerequisites

- Ubuntu 24.04 droplet (2GB RAM, 1 vCPU)
- Managed PostgreSQL 16 database (1GB RAM, 10GB storage)
- Domain pointing to droplet IP (e.g., `api.camposocial.app`)
- Cloudflare for SSL (recommended) or DO Load Balancer

---

## Initial Server Setup

### 1. SSH into your droplet

```bash
ssh root@<your-droplet-ip>
```

### 2. Update system and install Docker

```bash
apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin git curl
systemctl enable docker
systemctl start docker
```

### 3. Create app directory

```bash
mkdir -p /opt/camposocial
cd /opt/camposocial
```

### 4. Clone your repository

```bash
git clone https://github.com/YOUR_USERNAME/camposocial-server.git app
cd app
```

### 5. Create .env.prod file

```bash
cat > .env.prod << 'EOF'
# Database - Get from DO Database dashboard > Connection details
DATABASE_URL=postgresql://doadmin:YOUR_PASSWORD@YOUR_DB_HOST:25060/defaultdb?sslmode=require

# Secrets - Generate with: openssl rand -hex 32
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-here

# Cloudflare R2 Storage
AWS_ACCESS_KEY_ID=your-r2-access-key
AWS_SECRET_ACCESS_KEY=your-r2-secret-key
AWS_DEFAULT_REGION=auto
R2_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET_NAME=camposocial

# IntaSend Payments
INTASEND_API_KEY=your-intasend-api-key
INTASEND_PUBLISHABLE_KEY=your-intasend-publishable-key
INTASEND_WEBHOOK_SECRET=your-webhook-secret
INTASEND_SANDBOX=false
BADGE_PAYMENT_PROVIDER=intasend

# URLs
FRONTEND_URL=https://camposocial.app
SELLER_DASHBOARD_URL=https://seller.camposocial.app
CORS_ALLOWED_ORIGINS=https://camposocial.app,https://www.camposocial.app

# Redis (uses local container)
REDIS_URL=redis://redis:6379/0
EOF

chmod 600 .env.prod
```

---

## First Deployment

### 1. Build and deploy

```bash
cd /opt/camposocial/app
docker build -t camposocial-server:latest .
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### 2. Check logs

```bash
# Check migration logs
docker compose -f docker-compose.prod.yml logs migrate

# Check app logs
docker compose -f docker-compose.prod.yml logs app -f
```

### 3. Verify deployment

```bash
curl http://localhost:5000/camposocial/api/
```

---

## Future Deployments

### With Model/Schema Changes (Migrations)

```bash
cd /opt/camposocial/app
git pull
docker build -t camposocial-server:latest .
docker compose -f docker-compose.prod.yml --env-file .env.prod down
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Or use the deploy script:

```bash
./scripts/deploy.sh
```

### Code-Only Changes (No Migrations)

```bash
cd /opt/camposocial/app
git pull
docker build -t camposocial-server:latest .
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --no-deps app
```

Or use:

```bash
./scripts/deploy.sh --code-only
```

---

## Local Development Migration Workflow

### When you change models.py:

```bash
# 1. Generate migration
flask db migrate -m "Add new field to users"

# 2. REVIEW the generated file in migrations/versions/

# 3. Test locally
flask db upgrade
flask db downgrade  # Verify rollback works
flask db upgrade    # Re-apply

# 4. Commit
git add migrations/versions/*.py
git commit -m "Add migration: new field"
git push
```

---

## Cloudflare SSL Setup

1. Add your domain to Cloudflare
2. Point `api.camposocial.app` A record to your droplet IP
3. In Cloudflare SSL/TLS settings, set mode to **Full (strict)**
4. Done - Cloudflare handles SSL termination

---

## Useful Commands

```bash
# View all containers
docker ps -a

# View app logs
docker compose -f docker-compose.prod.yml logs app -f

# Restart app only
docker compose -f docker-compose.prod.yml restart app

# Stop everything
docker compose -f docker-compose.prod.yml down

# Check database migration status
docker exec -it camposocial-server flask db current

# Connect to database
docker exec -it camposocial-server flask shell
```

---

## Troubleshooting

### Migration failed
```bash
# Check migration logs
docker compose -f docker-compose.prod.yml logs migrate

# If needed, connect to DB and fix manually
psql "YOUR_DATABASE_URL"
```

### App won't start
```bash
# Check logs
docker compose -f docker-compose.prod.yml logs app --tail 100

# Check if migration succeeded
docker compose -f docker-compose.prod.yml logs migrate
```

### Database connection issues
- Verify DATABASE_URL in .env.prod
- Check that droplet IP is in database trusted sources
- Ensure `?sslmode=require` is in the URL
