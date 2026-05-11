# Deployment Runbook

How to take this from a git repo to a working production deployment with
~5 real parishioners using it on Sunday morning. Targets a single VPS;
total cost ~$5/month.

## Architecture

```
                 [ DNS: bulletin.example.org ──► VPS public IP ]
                                  │
                                  ▼
                              [ Caddy ]    :80  :443  (TLS, public)
                             /        \
                            ▼          ▼
                  [ FastAPI api ]    [ /srv/pwa static files ]
                       :8000             (mounted from dist/)
                          │
                          ▼
                  [ /data volume ]
                   harness.db + pdfs/
                          ▲
                          │ writes
                          │
                  [ harness container ]
                   (cron-triggered, exits after each run)
                          │ calls
                          ▼
                  api.anthropic.com (parser)
                  files.ecatholic.com (bulletins)
```

The data volume is the only durable state. Lose it, lose everything.

## Prerequisites

1. **A domain.** Real one with DNS you control. Subdomain is fine
   (`bulletin.example.org`).
2. **A VPS.** Hetzner CX22 (~€4/mo), DigitalOcean basic droplet (~$5/mo),
   or equivalent. Ubuntu 24.04 LTS recommended. 1 GB RAM is enough.
3. **An Anthropic API key.** From console.anthropic.com. Used by the
   weekly parser; expect well under $1/month for a handful of parishes.
4. **An email address** for Let's Encrypt notifications. Don't use a
   personal address you might lose access to.

## One-time host setup

SSH in as root (or your sudo user) and run:

```bash
# Docker + compose plugin (Ubuntu 24.04)
apt-get update
apt-get install -y docker.io docker-compose-v2 git

# Create the deploy user
useradd -m -s /bin/bash -G docker bulletin
mkdir -p /opt/bulletin
chown bulletin:bulletin /opt/bulletin

# Switch to the deploy user for everything else
su - bulletin
cd /opt/bulletin
```

Point your DNS at the box BEFORE the next step (Caddy uses the domain to
issue a Let's Encrypt cert; if DNS isn't right, the cert request fails).

## Initial deploy

```bash
cd /opt/bulletin
git clone <this repo's url> .

# Build the PWA so Caddy has something to serve. We do this on the host
# rather than in a Docker layer because the build is fast and the output
# is just static files that get bind-mounted into the caddy container.
( cd mobile_app && npm ci && npm run build )

# Configure secrets
cp .env.example .env
$EDITOR .env
# Set DOMAIN, ACME_EMAIL, ANTHROPIC_API_KEY. Save.

# Bring everything up. First boot pulls the api image (~150MB), starts
# Caddy, requests a Let's Encrypt cert. The first request to the cert
# endpoint takes a few seconds.
docker compose up -d --build

# Verify
docker compose ps             # all running, no restart loops
docker compose logs caddy     # look for 'certificate obtained successfully'
curl -fs https://$DOMAIN/api/health    # → {"ok":true}
```

You should now be able to open `https://your-domain/` in a browser and
see the PWA load. The Today screen will 404 the bulletin endpoint
(because no parishes are loaded yet) — that's expected.

## Seed one parish

```bash
# Add the parish
docker compose run --rm --no-deps harness \
    python -m bulletin_parser.harness \
    --db /data/harness.db --pdfs /data/pdfs \
    add-parish \
      --id ny-old-st-patricks \
      --name "Basilica of St. Patrick's Old Cathedral" \
      --host-kind ecatholic --ecatholic-id 11778 \
      --diocese "Archdiocese of New York" --city "New York" --state NY

# Geocode it so search works
docker compose run --rm --no-deps harness \
    python -m bulletin_parser.seeder geocode \
    --db /data/harness.db --pdfs /data/pdfs

# Pull this week's bulletin and parse it. This makes the only real
# Anthropic API call in the whole flow.
docker compose run --rm harness
```

After this last command finishes, the Today screen should render real
content. Open the app in a browser, confirm.

## Set up the weekly cron

On the host as the bulletin user:

```bash
crontab -e
```

Add:

```cron
# Saturday 6pm UTC — runs the harness against all active parishes.
# Times in your local zone; tune to whatever's reasonable for your TZ.
0 18 * * SAT /opt/bulletin/ops/cron-harness.sh

# Sunday 3am — backup. After the harness has stabilized weekly data,
# before parishioners start opening the app for Sunday morning.
0 3 * * SUN /opt/bulletin/ops/backup.sh
```

## Day-to-day operations

```bash
# Quick health check
./ops/status.sh

# Tail logs
docker compose logs -f api
ls -t logs/harness-*.log | head -1 | xargs less  # most recent harness run

# Manual harness run (e.g. a parish posted late on Saturday)
docker compose run --rm harness

# Manual backup
./ops/backup.sh

# Restore from a backup (DESTRUCTIVE — wipes current data)
./ops/restore.sh ./backups/bulletin-20260511T030000Z.tar.gz
```

## Deploying updates

Once GitHub Actions is configured (see `.github/workflows/ci.yml`), the
flow is:

```bash
# Local: tag and push
git tag v0.2.0
git push --tags

# Wait for CI to build the image (a few minutes)

# Production host:
cd /opt/bulletin
git pull
docker compose pull              # gets the newly-built image
docker compose up -d             # recreates containers with the new image
./ops/status.sh                  # verify
```

For PWA-only changes (no Python code touched), it's faster to skip the
image and just rebuild static files:

```bash
git pull
( cd mobile_app && npm ci && npm run build )
docker compose restart caddy     # picks up the new dist/
```

## Monitoring and alerting

For a 5-user test, manual checks are enough. Two things to watch:

1. **Did Saturday's harness succeed?** `tail logs/harness-*.log`. If you
   see "fetch errors > 0" or no log file at all, investigate Sunday
   morning before parishioners hit the app.
2. **Is the API responding?** `curl -fsS https://$DOMAIN/api/health`.
   For real monitoring, point UptimeRobot or BetterUptime at that URL.

Beyond 5 users, plan for: log aggregation (any of Loki/Axiom/Logtail),
uptime monitoring with on-call paging, and per-parish parse-success
metrics surfaced somewhere visible.

## Ethics and politeness

We're fetching bulletins from real parishes from a real CDN. The system
is polite by default (1 req/sec/host, identifying User-Agent, respects
robots.txt) but there's a relationship layer the code doesn't enforce:

- **For each parish you onboard for real testing, email the pastor or
  parish office.** A two-sentence "hi, I'm building an app that makes
  your weekly bulletin easier to read on phones; you'll see weekly
  fetches from BulletinParserBot in your logs; reply if you'd like me
  to stop" goes a long way.
- **Don't mass-onboard before talking to the diocese.** A friendly
  partnership with one diocese is worth more than scraping a hundred
  parishes uninvited.

## Failure modes and recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| Cert acquisition fails on first boot | DNS not propagated | Wait, or `dig $DOMAIN` to confirm |
| `harness` exits with auth error | ANTHROPIC_API_KEY missing/wrong | Check `.env`, restart |
| `harness` says "discovery_failed" | Parish CDN URL changed | Check `bulletins_url` in roster |
| API returns 500 on a specific parish | Parse error in latest bulletin | Reparse with newer model, or hand-correct the bulletin row |
| Disk full | PDF dir growing unbounded | Add retention to `ops/`, prune `/data/pdfs/{parish}/{old-year}` |

For anything else, `./ops/status.sh` is the entry point.

## Decommissioning

If we shut this down:

```bash
# Back up first
./ops/backup.sh
scp backups/*.tar.gz off-vps:/somewhere/safe/

# Bring everything down
docker compose down -v          # -v also nukes the data volume

# Destroy the VPS via your provider's console
```

The backup tarball is self-contained. If you ever want to bring this
back up, follow this runbook from the top, then `./ops/restore.sh` your
saved tarball.
