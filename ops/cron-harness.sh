#!/usr/bin/env bash
#
# Saturday-evening harness runner. Invoked by host cron:
#
#   0 18 * * SAT cd /opt/bulletin && /opt/bulletin/ops/cron-harness.sh
#
# This is deliberately a thin wrapper around `docker compose run` so
# we can see exactly what cron is going to execute, log it sanely, and
# fail loudly if anything's wrong.

set -euo pipefail

cd "$(dirname "$0")/.."

LOG_DIR="${LOG_DIR:-./logs}"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/harness-$(date -u +%Y%m%dT%H%M%SZ).log"

{
    echo "=== Harness run at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    docker compose run --rm harness
    echo "=== Done ==="
} 2>&1 | tee "${LOG}"

# Keep last ~12 weekly logs (3 months of history).
find "${LOG_DIR}" -maxdepth 1 -name 'harness-*.log' -mtime +90 -delete
