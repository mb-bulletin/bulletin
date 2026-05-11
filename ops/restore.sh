#!/usr/bin/env bash
#
# Restore the data volume from a backup tarball produced by backup.sh.
#
# Usage: ./ops/restore.sh ./backups/bulletin-20260511T...tar.gz
#
# This stops the api and harness containers (Caddy stays up so visitors
# get a friendly error instead of connection refused), wipes /data, and
# restores from the tarball. The api auto-reopens the DB on the next
# request.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <backup.tar.gz>" >&2
    exit 2
fi

BACKUP="$1"
if [[ ! -f "${BACKUP}" ]]; then
    echo "Backup file not found: ${BACKUP}" >&2
    exit 2
fi

echo "WARNING: this will replace the contents of the data volume."
echo "Backup to restore: ${BACKUP}"
read -p "Type 'yes' to continue: " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "Aborted."
    exit 1
fi

# Take the API down so nothing's reading the DB during the restore
docker compose stop api

# Restore into a throwaway helper container so we don't depend on
# whether the api image happens to be running
docker run --rm \
    -v bulletin_data:/data \
    -v "$(realpath "$(dirname "${BACKUP}")")":/backup:ro \
    alpine sh -c "
        set -e
        cd /data
        rm -rf harness.db harness.db-* pdfs .snapshot
        tar -xzf /backup/$(basename "${BACKUP}")
        # The tarball stores the DB under .snapshot/; promote it.
        if [ -f .snapshot/harness.db ]; then
            mv .snapshot/harness.db harness.db
            rm -rf .snapshot
        fi
    "

docker compose start api
echo "Restore complete. Run 'docker compose logs api' to check."
