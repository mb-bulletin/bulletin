#!/usr/bin/env bash
#
# Back up the production data volume to a timestamped tarball.
#
# What we back up:
#   - harness.db          (the SQLite database — every bulletin we've parsed)
#   - pdfs/               (every PDF we've fetched)
#
# What we DON'T back up:
#   - the API itself (rebuild from git)
#   - Caddy state (re-issued from Let's Encrypt; only a problem if we
#     also need to back up to avoid LE rate limits, which we don't yet)
#   - eval_runs/ (kept on the developer's machine, not on the server)
#
# Why SQLite's online backup API rather than just `cp`: cp on a live DB
# can produce a torn file if writes are in flight. `sqlite3 .backup`
# is the safe way and works while the API is running.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/bulletin-${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

# Run the backup inside the running api container so we use the same
# volume mount and don't have to coordinate filesystem perms.
echo "Snapshotting SQLite via online backup API..."
docker compose exec -T api python -c "
import sqlite3, os
src = sqlite3.connect('/data/harness.db')
os.makedirs('/data/.snapshot', exist_ok=True)
dst = sqlite3.connect('/data/.snapshot/harness.db')
src.backup(dst)
dst.close()
src.close()
print('snapshot OK')
"

echo "Building tarball at ${OUT}..."
docker compose exec -T api tar -czf - -C /data .snapshot/harness.db pdfs/ \
    > "${OUT}"
docker compose exec -T api rm -rf /data/.snapshot

SIZE=$(du -h "${OUT}" | cut -f1)
echo "Backup written: ${OUT} (${SIZE})"

# Retention: keep the last 14 daily backups. Beyond that, we assume
# anything important has been mirrored offsite.
find "${BACKUP_DIR}" -maxdepth 1 -name 'bulletin-*.tar.gz' -mtime +14 -delete
echo "Old backups (>14d) pruned."
