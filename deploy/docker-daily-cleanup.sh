#!/bin/bash
# docker-daily-cleanup.sh
# Installed by deploy-production.yml — runs daily via cron at 03:00
# Reclaims Docker disk space: stopped containers, dangling images, build cache, unused volumes/networks
#
# Cron entry: /etc/cron.d/docker-cleanup
#   0 3 * * * root /usr/local/bin/docker-daily-cleanup.sh

set -euo pipefail

LOG_FILE="/var/log/docker-cleanup.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
KEEP_CACHE_BYTES=1073741824   # 1 GB of build cache to keep

log() { echo "[$TIMESTAMP] $*" | tee -a "$LOG_FILE"; }

log "========================================="
log "Docker daily cleanup — START"
log "========================================="

disk_before=$(df -h / | awk 'NR==2{print $3"/"$2" ("$5" used)"}')
log "Disk before: $disk_before"

# --- 1. Remove stopped/exited containers ---
log ">> Pruning stopped containers..."
docker container prune -f 2>&1 | tee -a "$LOG_FILE"

# --- 2. Remove dangling (untagged) images left from failed/superseded builds ---
log ">> Pruning dangling images..."
docker image prune -f 2>&1 | tee -a "$LOG_FILE"

# --- 3. Remove unused images not referenced by any container (older than 24h) ---
log ">> Pruning unused images (older than 24h)..."
docker image prune -a -f --filter "until=24h" 2>&1 | tee -a "$LOG_FILE"

# --- 4. Trim build cache — keep the most recent 1 GB ---
log ">> Pruning build cache (keeping ${KEEP_CACHE_BYTES} bytes)..."
docker builder prune --keep-storage "$KEEP_CACHE_BYTES" -f 2>&1 | tee -a "$LOG_FILE"

# --- 5. Remove unused networks ---
log ">> Pruning unused networks..."
docker network prune -f 2>&1 | tee -a "$LOG_FILE"

# --- 6. Remove anonymous volumes not attached to any container ---
log ">> Pruning unused anonymous volumes..."
docker volume prune -f 2>&1 | tee -a "$LOG_FILE"

# --- 7. Trim systemd journal logs ---
log ">> Trimming systemd journal (keep 50M)..."
journalctl --vacuum-size=50M 2>&1 | tee -a "$LOG_FILE"

# --- 8. Clear old btmp (failed SSH login log) if over 10MB ---
BTMP_SIZE=$(stat -c%s /var/log/btmp 2>/dev/null || echo 0)
if [ "$BTMP_SIZE" -gt 10485760 ]; then
    log ">> Truncating /var/log/btmp (${BTMP_SIZE} bytes)..."
    truncate -s 0 /var/log/btmp
fi

disk_after=$(df -h / | awk 'NR==2{print $3"/"$2" ("$5" used)"}')
log "Disk after:  $disk_after"
log "========================================="
log "Docker daily cleanup — DONE"
log "========================================="
