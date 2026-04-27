# GitHub Actions Deployment Setup

## Overview
This document outlines the required secrets and setup for GitHub Actions CI/CD deployments to production.

## Required Repository Secrets

Add these 3 secrets to your GitHub repository at: **Settings → Secrets and variables → Actions**

### 1. `DO_SERVER_IP`
**Description:** Your production server's public IP address

**Example:** `164.90.123.45`

**Where to find it:**
```bash
# On your server, run:
hostname -I
# or
curl -s https://api.ipify.org
```

---

### 2. `DO_USER`
**Description:** SSH user to connect to the server

**Value:** `root`

**Note:** This is typically the root user for Digital Ocean / VPS servers

---

### 3. `DO_SSH_PRIVATE_KEY`
**Description:** SSH private key for GitHub Actions to authenticate with your server

**How to generate on your server:**

```bash
# SSH into your server, then run:
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""

# View the private key (copy entire output)
cat ~/.ssh/github_deploy

# Verify the public key was created
cat ~/.ssh/github_deploy.pub
```

**Output format:** Should start with `-----BEGIN OPENSSH PRIVATE KEY-----` and end with `-----END OPENSSH PRIVATE KEY-----`

**Add to authorized_keys (IMPORTANT):**
```bash
# On the server:
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**Then copy the private key to GitHub:**
1. Go to your repo → **Settings → Secrets and variables → Actions**
2. Click **"New repository secret"**
3. Name: `DO_SSH_PRIVATE_KEY`
4. Paste the entire private key (including `-----BEGIN/END-----` lines)
5. Click **"Add secret"**

---

## Workflow Overview

The deployment workflow (`.github/workflows/deploy-production.yml`) performs:

### Jobs:
1. **Lint** - Validates workflow files (prevents dangerous Docker commands)
2. **Test Backend** - Runs Python tests with pytest
3. **Build Flutter** - Compiles Flutter web app for release
4. **Deploy to Production** - Syncs code, builds containers, runs migrations, health checks

### Deployment Steps:
```
1. Tests backend (Python)
   ↓
2. Builds Flutter web
   ↓
3. Syncs code to server via rsync
   ↓
4. Stops old containers
   ↓
5. Cleans disk space
   ↓
6. Rebuilds Docker images
   ↓
7. Starts containers
   ↓
8. Waits for database (30s max)
   ↓
9. Runs Alembic migrations
   ↓
10. Health checks (Backend, Admin Portal, Flutter Web, Customer UI)
    ↓
11. Auto-rollback on failure (reverts previous image)
```

---

## Key Features

### ✅ Automatic Triggers
- **On push to main branch** - Auto-deploys
- **Manual trigger** - Via GitHub UI (Actions tab → "Deploy Pinplot to Production" → "Run workflow")

### ✅ Health Checks
Automatically verifies all services are healthy:
- Backend: `http://{DO_SERVER_IP}:8001/api/health`
- Admin Portal: `http://{DO_SERVER_IP}:3010`
- Flutter Web: `http://{DO_SERVER_IP}:3012`
- Customer UI: `http://{DO_SERVER_IP}:3011`

### ✅ Auto-Rollback
If health checks fail, the workflow automatically:
1. Logs container status and backend logs
2. Reverts to the previous Docker image
3. Restarts containers with the previous version
4. Notifies in workflow run

### ✅ Database Migrations
Automatically runs Alembic migrations with retries:
```bash
docker compose exec -T backend alembic upgrade head
```

### ✅ Daily Docker Cleanup
Installs a cron job that runs at 03:00 UTC daily:
```bash
/usr/local/bin/docker-daily-cleanup.sh
```
Cleans: dangling images, stopped containers, unused volumes

---

## Environment Variables (.env files)

⚠️ **IMPORTANT:** `.env` files are **NEVER** managed by GitHub Actions. They must be manually created on the server:

### Location: `/root/pinplot/gps-tracker/.env`
```
DATABASE_URL=postgresql://...
SECRET_KEY=...
SENDGRID_API_KEY=...
MZONE_CLIENT_ID=...
# etc.
```

### Location: `/root/pinplot/gps-tracker/backend/.env`
```
DATABASE_URL=...
SECRET_KEY=...
# etc.
```

**Setup on server (manual):**
```bash
ssh root@{DO_SERVER_IP}
cd ~/pinplot/gps-tracker
nano .env  # Create and paste your environment variables
chmod 600 .env

cd backend
nano .env
chmod 600 .env
```

---

## Troubleshooting

### Workflow fails at "Setup SSH"
**Cause:** `DO_SSH_PRIVATE_KEY` secret not set or invalid

**Fix:**
1. Verify the private key is in your repo secrets
2. Ensure the private key is valid (includes BEGIN/END lines)
3. Check public key is in server's `~/.ssh/authorized_keys`

### Workflow fails at "Sync code to server"
**Cause:** Server IP or user is incorrect or SSH key doesn't have permissions

**Debug:**
```bash
# On local machine, test SSH connection:
ssh -i ~/.ssh/github_deploy root@{DO_SERVER_IP} "echo 'SSH works'"
```

### Workflow fails at "Health checks"
**Cause:** Containers failed to start or migrations failed

**Fix:**
1. SSH to server: `ssh root@{DO_SERVER_IP}`
2. Check logs: `docker compose logs -f backend`
3. Check status: `docker compose ps`
4. Manually restart: `docker compose up -d`

### Workflow fails at "Run tests"
**Cause:** Backend tests are failing

**Fix:**
1. Fix the failing tests locally
2. Push to main branch
3. Workflow will retry

---

## Manual Deployment (Fallback)

If GitHub Actions fails repeatedly:

```bash
# SSH to server
ssh root@{DO_SERVER_IP}

# Go to project
cd ~/pinplot/gps-tracker

# Use manual deployment script
bash deploy/quick-restart.sh

# Or manual steps:
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose exec backend alembic upgrade head
```

---

## For New Apps

When setting up GitHub Actions for new applications:

1. **Generate SSH key** on server (Ed25519 format)
2. **Add to authorized_keys** on server
3. **Create 3 GitHub Secrets** (`DO_SERVER_IP`, `DO_USER`, `DO_SSH_PRIVATE_KEY`)
4. **Create `.github/workflows/deploy-production.yml`** workflow file
5. **Create `.env` files** manually on server
6. **Test with a push** to main branch
7. **Monitor Actions tab** for success/failure

---

## Security Notes

- ✅ Private keys are encrypted in GitHub secrets
- ✅ `.env` files are **never** stored in git or Actions
- ✅ SSH key rotation recommended every 6 months
- ✅ Use `StrictHostKeyChecking=no` only for known hosts
- ✅ Workflow logs are visible to repo members (no secrets printed)

---

## Files Modified

- `.github/workflows/deploy-production.yml` - Main deployment workflow
- `.github/workflows/rollback-production.yml` - Manual rollback trigger
- `deploy/docker-daily-cleanup.sh` - Installed as cron job on server

---

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [webfactory/ssh-agent](https://github.com/webfactory/ssh-agent)
- [Docker Compose](https://docs.docker.com/compose/)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)
