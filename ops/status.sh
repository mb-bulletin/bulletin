#!/usr/bin/env bash
#
# One-stop quick check that the production system is healthy.
# Run it from the deploy directory on the production host.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== docker compose services ==="
docker compose ps

echo ""
echo "=== API health ==="
docker compose exec -T api curl -sf http://localhost:8000/health \
    && echo "  api OK" || echo "  api FAILED"

echo ""
echo "=== Harness health summary (last 7 days) ==="
docker compose run --rm --no-deps harness \
    python -m bulletin_parser.harness --db /data/harness.db --pdfs /data/pdfs status

echo ""
echo "=== Disk usage ==="
docker compose exec -T api du -sh /data /data/pdfs 2>/dev/null || true

echo ""
echo "=== Recent backups ==="
ls -lh ./backups/*.tar.gz 2>/dev/null | tail -5 || echo "  (no backups yet)"
