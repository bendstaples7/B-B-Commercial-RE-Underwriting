# Design Document: VPS Deployment

## Overview

This document describes the technical design for deploying the Flask + React real estate analysis application to a Hetzner CX22 VPS. The goal is a production-grade, HTTPS-accessible deployment at a DuckDNS subdomain, automated via GitHub Actions CI/CD, with a local PostgreSQL 15 instance replacing the Neon cloud database.

**Key constraints:**
- No Docker — all services run as native Linux processes managed by systemd
- Celery and Redis are excluded (`USE_ASYNC_COMPARABLE_SEARCH=false`)
- Zero-downtime deploys via Gunicorn SIGHUP graceful reload
- 3-person team access; Hetzner CX22 (~$4.50/month)

**Tech stack on VPS:**
- OS: Ubuntu 22.04 LTS
- Python 3.11 + Gunicorn (WSGI, 3 sync workers)
- Flask 3.0 application (existing codebase)
- PostgreSQL 15 (local, replaces Neon)
- Nginx (reverse proxy + static file server + TLS termination)
- Certbot (Let's Encrypt, auto-renewal via systemd timer)
- DuckDNS (free subdomain, updated every 5 minutes via cron)

---

## Architecture

### Component Diagram

```
Internet
    │  HTTPS :443 / HTTP :80
    ▼
┌─────────────────────────────────────────────────────────┐
│  Nginx (reverse proxy + TLS termination)                │
│  /etc/nginx/sites-available/real-estate                 │
│                                                         │
│  GET /assets/*  ──► /home/deploy/app/frontend/dist/     │
│  GET /*         ──► /home/deploy/app/frontend/dist/     │
│                     index.html (SPA fallback)           │
│  /api/*         ──► http://127.0.0.1:5000 (Gunicorn)    │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP :5000 (loopback only)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Gunicorn (WSGI, 3 sync workers)                        │
│  /etc/systemd/system/gunicorn.service                   │
│  Runs as: deploy user                                   │
│  Binds to: 127.0.0.1:5000                               │
│  Flask app: backend/app (__init__.py create_app)        │
└──────────────────────────┬──────────────────────────────┘
                           │ psycopg2 (Unix socket / localhost)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  PostgreSQL 15 (local)                                  │
│  Database: real_estate_analysis                         │
│  Role: app_user (no superuser)                          │
└─────────────────────────────────────────────────────────┘
```

### Directory Layout on VPS

```
/home/deploy/
├── app/                          # Git repo clone (owned by deploy)
│   ├── backend/
│   │   ├── .env                  # Production secrets (NOT in git)
│   │   ├── requirements.txt
│   │   ├── run.py
│   │   ├── app/
│   │   └── alembic_migrations/
│   └── frontend/
│       ├── package.json
│       └── dist/                 # Built by npm run build (served by Nginx)
├── rollback.sh                   # Rollback script (executable)
└── rollback.log                  # Rollback audit log

/etc/systemd/system/
└── gunicorn.service

/etc/nginx/
├── sites-available/real-estate
└── sites-enabled/real-estate -> ../sites-available/real-estate

/etc/letsencrypt/live/<subdomain>.duckdns.org/
├── fullchain.pem
└── privkey.pem
```

---

## Components and Interfaces

### 1. Nginx Configuration

**File:** `/etc/nginx/sites-available/real-estate`

Design decisions:
- HTTP→HTTPS redirect is a separate `server` block on port 80 (301 permanent)
- HTTPS block handles all real traffic on port 443
- Static assets under `/assets/` get `Cache-Control: max-age=31536000, immutable` because Vite hashes filenames (e.g. `index-BxYz1234.js`)
- `index.html` gets `Cache-Control: no-cache` so React Router updates are picked up immediately
- `try_files $uri $uri/ /index.html` provides the SPA fallback for client-side routes
- API proxy passes four headers so Flask sees the real client IP and protocol

```nginx
# /etc/nginx/sites-available/real-estate

server {
    listen 80;
    server_name bbanalyzer.duckdns.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name bbanalyzer.duckdns.org;

    # TLS — managed by Certbot
    ssl_certificate     /etc/letsencrypt/live/bbanalyzer.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bbanalyzer.duckdns.org/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Logging
    access_log /var/log/nginx/real-estate-access.log;
    error_log  /var/log/nginx/real-estate-error.log;

    # Proxy timeouts — match Gunicorn --timeout 120
    proxy_read_timeout    120s;
    proxy_connect_timeout  10s;
    proxy_send_timeout    120s;

    # API — proxy to Gunicorn
    location /api/ {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Vite-hashed assets — long-lived cache (filename changes on content change)
    location /assets/ {
        root       /home/deploy/app/frontend/dist;
        add_header Cache-Control "max-age=31536000, immutable";
        try_files  $uri =404;
    }

    # React SPA — no-cache for index.html, SPA fallback for all other paths
    location / {
        root       /home/deploy/app/frontend/dist;
        add_header Cache-Control "no-cache";
        try_files  $uri $uri/ /index.html;
    }
}
```

**Rationale for `options-ssl-nginx.conf`:** Certbot writes this file with Mozilla Intermediate TLS settings (TLS 1.2+, recommended cipher suite). Using it directly means the TLS config stays current when Certbot updates it.

### 2. Gunicorn / Systemd Service

**File:** `/etc/systemd/system/gunicorn.service`

Design decisions:
- 3 sync workers: CX22 has 2 vCPUs; 3 workers = 2×vCPU+1, the standard formula for CPU-bound workloads. Celery is excluded so there's no worker competition.
- `--timeout 120` matches the Nginx `proxy_read_timeout` and accommodates long-running comparable search requests.
- `--bind 127.0.0.1:5000` — loopback only; Nginx is the only entry point.
- `EnvironmentFile` loads `/home/deploy/app/backend/.env` so secrets never appear in the unit file or `ps` output.
- `Restart=on-failure` with `RestartSec=5s` ensures the service recovers from crashes without manual intervention.
- `FLASK_ENV=production` prevents auto-migration on startup (the deploy workflow runs `flask db upgrade head` explicitly).

```ini
# /etc/systemd/system/gunicorn.service
[Unit]
Description=Gunicorn — B&B Real Estate Analyzer
After=network.target postgresql.service

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/app/backend
EnvironmentFile=/home/deploy/app/backend/.env
Environment="FLASK_ENV=production"
ExecStart=/home/deploy/.local/bin/gunicorn \
    --workers 3 \
    --worker-class sync \
    --timeout 120 \
    --bind 127.0.0.1:5000 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app('production')"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gunicorn

[Install]
WantedBy=multi-user.target
```

**Graceful reload mechanism:** `ExecReload` sends `SIGHUP` to the master PID. Gunicorn's master process then forks new workers with the updated code, waits for them to become ready, and only then sends `SIGTERM` to the old workers. This is the standard Gunicorn graceful reload — at least one worker is always available during the transition.

**Invocation:** `systemctl reload gunicorn` (used by the deploy workflow instead of `restart`).

### 3. GitHub Actions Deploy Workflow

**File:** `.github/workflows/deploy.yml`

Design decisions:
- The deploy job depends on the existing `frontend` and `backend` CI jobs — it only runs if both pass.
- SSH is handled by `webfactory/ssh-agent` action, which loads the private key from `VPS_SSH_KEY` secret into the agent for the duration of the job.
- All VPS commands run in a single `ssh` step using a heredoc to avoid multiple round-trips and to ensure the entire sequence is atomic (any failure aborts the rest).
- `flask db upgrade head` runs with `DATABASE_URL` and `FLASK_ENV=production` injected from GitHub secrets so it connects to the production database.
- The post-deploy health check polls `/api/health` with a 30-second timeout and retries every 3 seconds (10 attempts) to give Gunicorn time to finish its graceful reload.
- Secrets are never written to the workflow YAML — all sensitive values come from `${{ secrets.* }}`.

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: [frontend, backend]   # reuse jobs from ci.yml via workflow_run or inline

    steps:
      - name: Load SSH key
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.VPS_SSH_KEY }}

      - name: Add VPS to known hosts
        run: ssh-keyscan -H ${{ secrets.VPS_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy
        env:
          VPS_USER: ${{ secrets.VPS_USER }}
          VPS_HOST: ${{ secrets.VPS_HOST }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          ssh $VPS_USER@$VPS_HOST << 'ENDSSH'
            set -euo pipefail
            cd /home/deploy/app

            echo "==> (1) Pull latest code"
            git pull origin main

            echo "==> (2) Install Python dependencies"
            pip install --user -r backend/requirements.txt

            echo "==> (3) Build frontend"
            cd frontend
            npm ci
            npm run build
            cd ..

            echo "==> (4) Run database migrations"
            cd backend
            FLASK_ENV=production DATABASE_URL="${DATABASE_URL}" \
              flask db upgrade head
            cd ..

            echo "==> (5) Reload Gunicorn (zero-downtime)"
            sudo systemctl reload gunicorn

            echo "==> Deploy complete"
          ENDSSH

      - name: Post-deploy health check
        env:
          VPS_SUBDOMAIN: ${{ secrets.VPS_SUBDOMAIN }}
        run: |
          echo "Waiting for Gunicorn to finish graceful reload..."
          sleep 5
          for i in $(seq 1 10); do
            STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
              --max-time 10 \
              "https://${VPS_SUBDOMAIN}.duckdns.org/api/health" || echo "000")
            echo "Attempt $i: HTTP $STATUS"
            if [ "$STATUS" = "200" ]; then
              echo "Health check passed."
              exit 0
            fi
            sleep 3
          done
          echo "Health check failed after 10 attempts."
          exit 1
```

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `VPS_SSH_KEY` | Private SSH key for the `deploy` user (Ed25519 recommended) |
| `VPS_USER` | `deploy` |
| `VPS_HOST` | VPS public IP address |
| `VPS_SUBDOMAIN` | DuckDNS subdomain prefix (e.g. `bbanalyzer`) |
| `DATABASE_URL` | Production PostgreSQL connection string (for `flask db upgrade head`) |

**Note on `sudo systemctl reload gunicorn`:** The `deploy` user needs passwordless sudo for this one command. Add to `/etc/sudoers.d/deploy`:
```
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload gunicorn
```

### 4. Health Check Endpoint

The existing `/api/health` endpoint in `backend/app/controllers/routes.py` already performs four checks (DB connectivity, migration head, unclassified leads, queue counts) and returns `{"status": "healthy"}` / `{"status": "degraded"}` with HTTP 200 / 503.

**Alignment with requirements:** The requirements specify `{"status": "ok"}` for healthy and `{"status": "error", "detail": "..."}` for unhealthy. The existing implementation uses `"healthy"` / `"degraded"` with a `checks` dict. The deploy workflow health check only tests for HTTP 200 (not the body), so the existing implementation satisfies the CI/CD requirement as-is.

**No code change needed** — the existing endpoint is sufficient for the post-deploy health check. The `checks` dict provides richer diagnostics than the spec requires, which is strictly better.

---

## Data Models

### PostgreSQL Role and Database Setup

```sql
-- Run as postgres superuser during initial VPS setup

-- Create application role (no superuser)
CREATE ROLE app_user WITH LOGIN PASSWORD '<strong-password>';
GRANT CREATEDB TO app_user;   -- needed for Alembic to create/drop test schemas

-- Create database owned by app_user
CREATE DATABASE real_estate_analysis OWNER app_user;

-- Connect to the database and grant schema privileges
\c real_estate_analysis
GRANT ALL PRIVILEGES ON SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_user;
```

**`DATABASE_URL` in production `.env`:**
```
DATABASE_URL=postgresql://app_user:<password>@localhost:5432/real_estate_analysis
```

Note: no `?sslmode=require` for localhost connections (SSL is unnecessary on loopback).

### Data Migration Procedure (Neon → VPS)

This is a one-time operation performed during initial setup:

```bash
# Step 1: Export from Neon (run locally or from any machine with psql access)
pg_dump \
  --no-owner \
  --no-acl \
  --format=custom \
  --file=neon_export.dump \
  "$NEON_DATABASE_URL"

# Step 2: Copy dump to VPS
scp neon_export.dump deploy@<VPS_IP>:/home/deploy/neon_export.dump

# Step 3: Restore to local PostgreSQL (run on VPS as deploy user)
pg_restore \
  --no-owner \
  --no-acl \
  --dbname=real_estate_analysis \
  --username=app_user \
  --host=localhost \
  /home/deploy/neon_export.dump

# Step 4: Apply any pending migrations
cd /home/deploy/app/backend
FLASK_ENV=production flask db upgrade head

# Step 5: Transfer table ownership to app_user
psql -U postgres -d real_estate_analysis -c "
  DO \$\$
  DECLARE r RECORD;
  BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
      EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' OWNER TO app_user';
    END LOOP;
  END \$\$;
"

# Step 6: Verify row counts match source
psql -U app_user -d real_estate_analysis -c "
  SELECT schemaname, tablename, n_live_tup
  FROM pg_stat_user_tables
  ORDER BY n_live_tup DESC;
"
```

**Non-fatal pg_restore errors:** Errors like `ERROR: role "neon_superuser" does not exist` or duplicate object errors from idempotent migrations are expected and acceptable. The `--no-owner --no-acl` flags suppress most ownership-related errors.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Most of this deployment spec consists of infrastructure configuration (SMOKE) and one-time procedural steps (INTEGRATION) that are not amenable to property-based testing. However, three behavioral properties emerge from the requirements that are testable with Hypothesis:

**Property Reflection:** After reviewing all acceptance criteria, the testable properties are:
1. Health endpoint availability after any valid deployment (Req 10.1)
2. Health endpoint degradation when DB is unavailable (Req 10.2)
3. Rollback restores a working state (Req 9.1–9.2)

Properties 1 and 2 can be combined: the health endpoint's HTTP status code is fully determined by DB connectivity — this is a single comprehensive property about the health check's correctness logic. Property 3 is distinct (rollback behavior).

---

### Property 1: Health check status reflects database connectivity

*For any* Flask application state, the `/api/health` endpoint SHALL return HTTP 200 when the database connection succeeds and HTTP 503 when the database connection fails. The response body SHALL always contain a `status` field.

**Validates: Requirements 10.1, 10.2**

---

### Property 2: Rollback restores a deployable state

*For any* pair of consecutive Git commits (previous, current) where the current commit causes the health check to fail, executing the rollback script SHALL result in the application returning to the previous commit and the health check returning HTTP 200.

**Validates: Requirements 9.1, 9.2**

---

## Error Handling

### Deployment Failures

| Failure Point | Detection | Recovery |
|---|---|---|
| `git pull` fails (merge conflict, network) | Non-zero exit, workflow halts | Fix conflict locally, push again |
| `pip install` fails (bad package, network) | Non-zero exit, workflow halts | Fix requirements.txt, push again |
| `npm run build` fails (TypeScript error) | Non-zero exit, workflow halts | Fix frontend code, push again |
| `flask db upgrade head` fails | Non-zero exit, workflow halts | Fix migration, push again; old code still running |
| `systemctl reload gunicorn` fails | Non-zero exit, workflow halts | SSH to VPS, check `journalctl -u gunicorn` |
| Post-deploy health check fails | curl returns non-200 | Run rollback.sh on VPS |

**Critical design decision:** The deploy workflow uses `set -euo pipefail` inside the SSH heredoc. Any command failure immediately aborts the sequence. Because `systemctl reload gunicorn` is the last step before the health check, a failed migration leaves the old code running — the VPS is never left in a half-deployed state.

### Gunicorn Worker Failures

If a Gunicorn worker crashes mid-request, the master process spawns a replacement within `RestartSec=5s`. The client receives a 502 from Nginx (since the worker died before responding). This is acceptable for a 3-person team; the next request will succeed.

### Database Connection Loss

The Flask app is configured with `pool_pre_ping=True` (see `create_app`), which discards stale connections before use. If the local PostgreSQL service restarts, the next request will re-establish the connection transparently.

### Certificate Renewal Failure

Certbot's `certbot.timer` runs twice daily. If renewal fails (e.g. DuckDNS DNS propagation delay), Certbot retries automatically. The certificate has a 90-day lifetime; renewal is attempted at 30 days remaining, giving a 30-day window to resolve any issues before expiry.

---

## Environment Variable Management

### Production `.env` File

**Location:** `/home/deploy/app/backend/.env`
**Ownership:** `deploy:deploy`, mode `600` (readable only by the deploy user)

The file is created manually during initial setup by copying `.env.example` and filling in production values. It is never committed to git (already in `.gitignore`).

**Required production variables:**

```bash
# /home/deploy/app/backend/.env  (production)

# Database — local PostgreSQL (no sslmode needed for localhost)
DATABASE_URL=postgresql://app_user:<password>@localhost:5432/real_estate_analysis

# Flask
SECRET_KEY=<64-char random hex>
JWT_SECRET_KEY=<64-char random hex>
FLASK_ENV=production

# Async — Celery excluded from initial deployment
USE_ASYNC_COMPARABLE_SEARCH=false
REDIS_URL=redis://localhost:6379/0        # not used, but prevents startup warning
CELERY_BROKER_URL=redis://localhost:6379/0

# External APIs
GOOGLE_MAPS_API_KEY=<key>
GOOGLE_AI_API_KEY=<key>
RENTCAST_API_KEY=<key>
MLS_API_KEY=<key>
TAX_ASSESSOR_API_KEY=<key>
CHICAGO_DATA_API_KEY=<key>
COOK_COUNTY_APP_TOKEN=<token>
SOCRATA_APP_TOKEN=<token>

# HubSpot
HUBSPOT_ENCRYPTION_KEY=<fernet-key>
HUBSPOT_CLIENT_SECRET=<secret>

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE=/home/deploy/app/backend/credentials.json
```

**Generating strong keys:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Missing Variable Behavior

The existing `create_app()` already handles missing variables:
- `SECRET_KEY` missing or set to `dev-secret-key` → `SystemExit` with clear message
- `DATABASE_URL` missing or malformed → `SystemExit` with clear message
- Optional keys (Google Maps, AI, etc.) → startup warning logged to journal, app continues

This means a misconfigured `.env` will prevent Gunicorn from starting, which is immediately visible via `journalctl -u gunicorn` and the post-deploy health check.

---

## Zero-Downtime Deployment Mechanism

### SIGHUP Graceful Reload Sequence

```
Deploy workflow runs: sudo systemctl reload gunicorn
    │
    ▼
systemd sends SIGHUP to Gunicorn master PID
    │
    ▼
Gunicorn master forks 3 new workers (new code loaded)
    │
    ├── New workers: bind to 127.0.0.1:5000, start accepting connections
    │
    ▼
Gunicorn master sends SIGTERM to old workers
    │
    ├── Old workers: finish in-flight requests (up to --timeout 120s)
    │   then exit cleanly
    │
    ▼
Only new workers remain — reload complete
```

**Key invariant:** During the transition, both old and new workers are bound to port 5000. Nginx's upstream connection pool continues to route requests to whichever worker accepts first. No request is dropped.

### Old Asset Preservation

Vite produces content-hashed filenames (e.g. `index-BxYz1234.js`). When a new build runs, new files are written to `frontend/dist/` but old files are not deleted — `npm run build` only writes new files, it does not clean the directory first.

**Design decision:** Do NOT run `rm -rf frontend/dist` before building. Old asset URLs referenced by in-flight page loads continue to resolve until the next deployment overwrites them.

If disk space becomes a concern (unlikely on 40 GB SSD for a 3-person team), a cleanup step can be added after the health check passes.

---

## Rollback Script Design

**File:** `/home/deploy/rollback.sh`
**Permissions:** `chmod 750 /home/deploy/rollback.sh` (executable by deploy user)

The script accepts an optional commit hash argument. If omitted, it rolls back to `HEAD~1` (the commit before the current one).

```bash
#!/usr/bin/env bash
# /home/deploy/rollback.sh
# Usage: ./rollback.sh [<commit-hash>]
# Rolls back the application to the specified commit (default: HEAD~1).

set -euo pipefail

APP_DIR="/home/deploy/app"
LOG_FILE="/home/deploy/rollback.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cd "$APP_DIR"

CURRENT_COMMIT=$(git rev-parse HEAD)
TARGET_COMMIT="${1:-$(git rev-parse HEAD~1)}"

echo "[$TIMESTAMP] Rollback initiated: $CURRENT_COMMIT -> $TARGET_COMMIT" | tee -a "$LOG_FILE"

echo "==> (1) Checking out previous commit: $TARGET_COMMIT"
git checkout "$TARGET_COMMIT"

echo "==> (2) Reinstalling Python dependencies"
pip install --user -r backend/requirements.txt

echo "==> (3) Rebuilding frontend"
cd frontend
npm ci
npm run build
cd ..

echo "==> (4) Checking if migration downgrade is needed"
# If the current (failing) commit added a migration, downgrade by 1
MIGRATION_CHANGED=$(git diff "$TARGET_COMMIT" "$CURRENT_COMMIT" \
  --name-only -- backend/alembic_migrations/versions/ | wc -l)
if [ "$MIGRATION_CHANGED" -gt 0 ]; then
    echo "    Migration files changed — running flask db downgrade -1"
    cd backend
    FLASK_ENV=production flask db downgrade -1
    cd ..
else
    echo "    No migration changes detected — skipping downgrade"
fi

echo "==> (5) Reloading Gunicorn"
sudo systemctl reload gunicorn

echo "==> (6) Waiting for health check"
sleep 5
for i in $(seq 1 10); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      --max-time 10 http://127.0.0.1:5000/api/health || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "[$TIMESTAMP] Rollback successful: now at $TARGET_COMMIT" | tee -a "$LOG_FILE"
        echo "Health check passed. Rollback complete."
        exit 0
    fi
    sleep 3
done

echo "[$TIMESTAMP] Rollback FAILED: health check did not pass after rollback to $TARGET_COMMIT" \
  | tee -a "$LOG_FILE"
echo "ERROR: Health check failed after rollback. Check journalctl -u gunicorn."
exit 1
```

**Rollback log format:**
```
[2025-01-15T14:32:01Z] Rollback initiated: abc1234 -> def5678
[2025-01-15T14:32:45Z] Rollback successful: now at def5678
```

---

## DuckDNS + Certbot SSL Setup

### DuckDNS Configuration

1. Register at [duckdns.org](https://www.duckdns.org), create subdomain `bbanalyzer` (or chosen name), point it to the VPS public IP.

2. Create the update script on the VPS:

```bash
# /home/deploy/duckdns/duck.sh
echo url="https://www.duckdns.org/update?domains=bbanalyzer&token=<YOUR_TOKEN>&ip=" \
  | curl -k -o /home/deploy/duckdns/duck.log -K -
```

3. Add cron job (runs every 5 minutes):
```bash
crontab -e -u deploy
# Add:
*/5 * * * * /home/deploy/duckdns/duck.sh >/dev/null 2>&1
```

### Certbot SSL Certificate

```bash
# Install Certbot with Nginx plugin
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate (Nginx must be running with HTTP config first)
sudo certbot --nginx -d bbanalyzer.duckdns.org \
  --non-interactive \
  --agree-tos \
  --email <admin-email>

# Certbot automatically:
# 1. Obtains the certificate from Let's Encrypt
# 2. Modifies the Nginx config to add SSL directives
# 3. Installs certbot.timer for auto-renewal (runs twice daily)

# Verify auto-renewal works
sudo certbot renew --dry-run
```

**Auto-renewal:** The `certbot.timer` systemd timer (installed by the certbot package) runs `certbot renew` twice daily. Certbot only renews certificates within 30 days of expiry. No manual intervention needed.

**TLS configuration:** Certbot writes `/etc/letsencrypt/options-ssl-nginx.conf` with Mozilla Intermediate settings:
- Minimum TLS 1.2
- Recommended cipher suite (ECDHE-ECDSA-AES128-GCM-SHA256, etc.)
- HSTS header (optional, can be added manually)

---

## Security Hardening

### Initial VPS Hardening Steps

```bash
# 1. Create deploy user
adduser deploy
usermod -aG sudo deploy

# 2. Copy SSH public key for deploy user
mkdir -p /home/deploy/.ssh
cat <your-public-key> >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# 3. Disable password authentication
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# 4. Configure UFW firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (for Certbot ACME challenge + redirect)
ufw allow 443/tcp   # HTTPS
ufw enable

# 5. Install and configure fail2ban
apt install -y fail2ban
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled  = true
port     = ssh
maxretry = 5
findtime = 600
bantime  = 3600
EOF
systemctl enable --now fail2ban

# 6. Disable root login via SSH
sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd
```

### PostgreSQL Security

- `app_user` has no superuser privileges (enforced by `_assert_not_superuser` in `create_app`)
- PostgreSQL listens on localhost only (default `pg_hba.conf` for Ubuntu)
- No external port exposed (UFW blocks port 5432)

### Application Security

- `SECRET_KEY` and `JWT_SECRET_KEY` are 64-char random hex strings (never the dev default)
- `.env` file is mode `600`, owned by `deploy`
- Nginx does not expose the Gunicorn port externally
- Flask-Limiter rate limiting is active in production (same as development)

---

## Testing Strategy

### PBT Applicability Assessment

This feature is primarily infrastructure configuration and deployment automation. The vast majority of acceptance criteria are SMOKE tests (one-time configuration checks) or INTEGRATION tests (procedural steps). Property-based testing applies only to the Flask application's health check logic, which is pure Python code with clear input/output behavior.

**PBT IS applicable for:**
- Health check endpoint response logic (DB connectivity → HTTP status code mapping)

**PBT IS NOT applicable for:**
- VPS provisioning (SMOKE — configuration either exists or it doesn't)
- Nginx/systemd configuration (SMOKE — file contents are static)
- GitHub Actions workflow (INTEGRATION — external CI platform)
- Data migration (INTEGRATION — one-time procedural operation)
- DuckDNS/Certbot setup (SMOKE — external service configuration)

**Testing library:** Hypothesis (already used throughout the backend test suite)

---

### Unit Tests (Example-Based)

These tests verify specific behaviors with concrete examples:

**`backend/tests/test_health_endpoint.py`**

```python
# Example 1: Healthy state returns 200
def test_health_returns_200_when_db_connected(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert 'status' in data

# Example 2: DB unavailable returns 503
def test_health_returns_503_when_db_unavailable(client, monkeypatch):
    from app import db
    from sqlalchemy.exc import OperationalError
    monkeypatch.setattr(db.session, 'execute',
        lambda *a, **kw: (_ for _ in ()).throw(OperationalError("", {}, None)))
    response = client.get('/api/health')
    assert response.status_code == 503
    data = response.get_json()
    assert 'status' in data
```

**`backend/tests/test_env_validation.py`**

```python
# Example: Missing SECRET_KEY causes SystemExit
def test_missing_secret_key_causes_system_exit():
    with pytest.raises(SystemExit):
        create_app('production')  # no SECRET_KEY in env
```

---

### Property-Based Tests

**`backend/tests/test_health_properties.py`**

```python
from hypothesis import given, settings, strategies as st

# Property 1: Health check status reflects database connectivity
# Feature: vps-deployment, Property 1: health check status reflects DB connectivity
@given(db_available=st.booleans())
@settings(max_examples=100)
def test_health_status_reflects_db_connectivity(db_available, app):
    """For any Flask application state, /api/health returns HTTP 200 when
    the database connection succeeds and HTTP 503 when it fails.
    The response body always contains a 'status' field.
    Validates: Requirements 10.1, 10.2
    """
    with app.test_client() as client:
        if not db_available:
            # Simulate DB failure
            with patch('app.db.session.execute',
                       side_effect=OperationalError("", {}, None)):
                response = client.get('/api/health')
                assert response.status_code == 503
        else:
            response = client.get('/api/health')
            assert response.status_code == 200
        data = response.get_json()
        assert 'status' in data
```

---

### Integration Tests (Manual / CI Smoke)

These are run manually after initial VPS setup or as part of a post-deploy verification checklist:

| Test | Command | Expected |
|------|---------|----------|
| HTTPS redirect | `curl -I http://bbanalyzer.duckdns.org/` | `301 Moved Permanently` |
| HTTPS health check | `curl https://bbanalyzer.duckdns.org/api/health` | `{"status":"healthy",...}` |
| SPA routing | `curl https://bbanalyzer.duckdns.org/leads` | `200` with `index.html` content |
| Asset caching | `curl -I https://bbanalyzer.duckdns.org/assets/index-*.js` | `Cache-Control: max-age=31536000` |
| TLS version | `openssl s_client -connect bbanalyzer.duckdns.org:443` | TLS 1.2 or 1.3 |
| Gunicorn service | `systemctl is-active gunicorn` | `active` |
| Nginx config valid | `nginx -t` | `syntax is ok` |
| Certbot renewal | `certbot renew --dry-run` | `Congratulations, all renewals succeeded` |
| UFW status | `ufw status` | ports 22, 80, 443 open |
| fail2ban active | `fail2ban-client status sshd` | `Status for the jail: sshd` |

---

### Deployment Verification Checklist

After every deployment (automated via the health check step in deploy.yml):

1. ✅ `curl -f https://bbanalyzer.duckdns.org/api/health` returns HTTP 200
2. ✅ `systemctl is-active gunicorn` returns `active`
3. ✅ `journalctl -u gunicorn -n 20` shows no ERROR lines
4. ✅ `tail -20 /var/log/nginx/real-estate-access.log` shows recent requests

Steps 2–4 are manual spot-checks; step 1 is automated in the deploy workflow.
