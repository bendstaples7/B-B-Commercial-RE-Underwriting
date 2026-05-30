# Implementation Plan: VPS Deployment

## Overview

Deploy the Flask + React real estate analysis application to a Hetzner CX22 VPS running Ubuntu 22.04 LTS. All services run as native Linux processes managed by systemd (no Docker). The plan covers: VPS hardening, PostgreSQL setup and data migration, Gunicorn systemd service, Nginx reverse proxy with TLS, DuckDNS + Certbot SSL, GitHub Actions CI/CD pipeline, health check endpoint, rollback script, and property-based tests for the health check logic.

Tasks are ordered so each step builds on the previous one. Infrastructure is established first, then the application layer, then automation, then observability and tests.

---

## Tasks

- [x] 1. Harden the VPS and install system dependencies
  - [x] 1.1 Create the `deploy` non-root user with sudo privileges and SSH key-only access
    - Add `deploy` user, copy SSH public key to `~/.ssh/authorized_keys` (mode 600)
    - Disable password authentication in `/etc/ssh/sshd_config` and restart sshd
    - Disable root SSH login (`PermitRootLogin no`)
    - _Requirements: 1.2, 1.3_

  - [x] 1.2 Configure UFW firewall and install fail2ban
    - Set UFW default deny inbound, allow outbound; open ports 22, 80, 443 only; enable UFW
    - Install `fail2ban`, write `/etc/fail2ban/jail.local` with `maxretry=5`, `findtime=600`, `bantime=3600` for the `sshd` jail; enable and start fail2ban
    - _Requirements: 1.4, 1.5_

  - [x] 1.3 Install Python 3.11, Node.js 20, PostgreSQL 15, Nginx, and Certbot via apt
    - Add NodeSource and PostgreSQL apt repositories as needed; install all packages in a single provisioning script
    - Verify each package is installed and at the correct version before marking complete
    - _Requirements: 1.6_

  - [x] 1.4 Clone the application repository and set ownership
    - Clone the Git repo to `/home/deploy/app` as the `deploy` user
    - Verify `deploy` owns all files under `/home/deploy/app`
    - _Requirements: 1.7_

- [x] 2. Set up PostgreSQL database and migrate data from Neon
  - [x] 2.1 Create the `app_user` PostgreSQL role and `real_estate_analysis` database
    - Run the SQL block from the design (`CREATE ROLE app_user`, `CREATE DATABASE real_estate_analysis OWNER app_user`, grant schema privileges and default privileges)
    - Verify `app_user` has no superuser flag (`\du` in psql)
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 Export data from Neon and restore to local PostgreSQL
    - Run `pg_dump --no-owner --no-acl --format=custom` against `$NEON_DATABASE_URL`; copy dump to VPS via `scp`
    - Run `pg_restore --no-owner --no-acl --dbname=real_estate_analysis --username=app_user --host=localhost` on the VPS
    - Document any non-fatal errors (duplicate objects, missing roles) as acceptable per Req 2.6
    - _Requirements: 2.3, 2.4, 2.6_

  - [x] 2.3 Apply Alembic migrations and transfer table ownership to `app_user`
    - Run `FLASK_ENV=production flask db upgrade head` from `/home/deploy/app/backend`
    - Execute the ownership-transfer PL/pgSQL block from the design to set all public tables to `app_user`
    - Verify row counts match source with `pg_stat_user_tables`
    - _Requirements: 2.5, 2.7_

- [x] 3. Create the production environment file
  - [x] 3.1 Write `/home/deploy/app/backend/.env` with all required production variables
    - Copy `backend/.env.example` to `/home/deploy/app/backend/.env`; fill in `DATABASE_URL` (localhost PostgreSQL), `SECRET_KEY` (64-char hex), `JWT_SECRET_KEY` (64-char hex), `FLASK_ENV=production`, `USE_ASYNC_COMPARABLE_SEARCH=false`, and all external API keys
    - Set file permissions to `600`, owned by `deploy:deploy`
    - _Requirements: 3.4, 3.8, 7.1, 7.2, 7.3_

- [x] 4. Install the Gunicorn systemd service
  - [x] 4.1 Write `/etc/systemd/system/gunicorn.service` and enable the service
    - Write the unit file exactly as specified in the design: `User=deploy`, `WorkingDirectory=/home/deploy/app/backend`, `EnvironmentFile=/home/deploy/app/backend/.env`, `Environment="FLASK_ENV=production"`, `ExecStart` with 3 sync workers `--timeout 120 --bind 127.0.0.1:5000`, `ExecReload=/bin/kill -s HUP $MAINPID`, `Restart=on-failure`, `RestartSec=5s`
    - Run `systemctl daemon-reload && systemctl enable gunicorn && systemctl start gunicorn`
    - Verify `systemctl is-active gunicorn` returns `active`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 4.2 Grant `deploy` passwordless sudo for `systemctl reload gunicorn`
    - Write `/etc/sudoers.d/deploy` with: `deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload gunicorn`
    - Verify `sudo systemctl reload gunicorn` succeeds without a password prompt as the `deploy` user
    - _Requirements: 6.3, 8.1_

- [x] 5. Build the React frontend and configure Nginx
  - [x] 5.1 Build the React frontend as the `deploy` user
    - Run `npm ci && npm run build` in `/home/deploy/app/frontend/`
    - Verify `frontend/dist/index.html` exists after the build
    - _Requirements: 4.1_

  - [x] 5.2 Write the Nginx site configuration and enable it
    - Write `/etc/nginx/sites-available/real-estate` with the exact config from the design: HTTP→HTTPS 301 redirect block; HTTPS block with TLS stubs, proxy timeouts (`proxy_read_timeout 120s`, `proxy_connect_timeout 10s`, `proxy_send_timeout 120s`), `/api/` proxy to `127.0.0.1:5000` with four `proxy_set_header` directives, `/assets/` with `Cache-Control: max-age=31536000, immutable`, `/` with `Cache-Control: no-cache` and `try_files $uri $uri/ /index.html`
    - Symlink to `sites-enabled`; disable the default site (`rm /etc/nginx/sites-enabled/default`)
    - Run `nginx -t` to validate; reload Nginx
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.4_

- [x] 6. Configure DuckDNS and obtain Let's Encrypt SSL certificate
  - [x] 6.1 Set up DuckDNS subdomain and cron-based IP update script
    - Register the subdomain at duckdns.org and point it to the VPS public IP
    - Create `/home/deploy/duckdns/duck.sh` with the curl update command; make it executable
    - Add the cron job `*/5 * * * * /home/deploy/duckdns/duck.sh >/dev/null 2>&1` for the `deploy` user
    - _Requirements: 5.1, 5.2_

  - [x] 6.2 Obtain the Let's Encrypt certificate via Certbot and verify auto-renewal
    - Install `certbot python3-certbot-nginx` via apt
    - Run `sudo certbot --nginx -d <subdomain>.duckdns.org --non-interactive --agree-tos --email <admin-email>`
    - Verify `certbot renew --dry-run` succeeds (confirms `certbot.timer` auto-renewal is functional)
    - Confirm Nginx now serves HTTPS and HTTP redirects to HTTPS
    - _Requirements: 5.3, 5.4, 5.5, 5.6_

- [x] 7. Checkpoint — verify the application is live
  - Confirm `curl -f https://<subdomain>.duckdns.org/api/health` returns HTTP 200
  - Confirm `systemctl is-active gunicorn` and `systemctl is-active nginx` both return `active`
  - Confirm `journalctl -u gunicorn -n 20` shows no ERROR lines
  - Ask the user if any issues arise before proceeding.

- [x] 8. Create the GitHub Actions deploy workflow
  - [x] 8.1 Write `.github/workflows/deploy.yml`
    - Create the file at `.github/workflows/deploy.yml` with the exact workflow from the design:
      - Trigger: `push` to `main`
      - `needs: [frontend, backend]` dependency on existing CI jobs
      - `webfactory/ssh-agent@v0.9.0` step loading `VPS_SSH_KEY` secret
      - `ssh-keyscan` step to add VPS to known hosts
      - Single SSH `Deploy` step with `set -euo pipefail` heredoc executing: `git pull origin main`, `pip install --user -r backend/requirements.txt`, `npm ci && npm run build` in `frontend/`, `FLASK_ENV=production DATABASE_URL="${DATABASE_URL}" flask db upgrade head`, `sudo systemctl reload gunicorn`
      - Post-deploy health check step: `sleep 5`, then poll `https://${VPS_SUBDOMAIN}.duckdns.org/api/health` up to 10 times with 3-second intervals, exit 0 on HTTP 200, exit 1 after 10 failures
    - All secrets referenced via `${{ secrets.* }}` — no hardcoded values
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 8.1, 8.2, 10.5_

  - [x] 8.2 Add required GitHub repository secrets
    - Document the five required secrets in the repo: `VPS_SSH_KEY`, `VPS_USER`, `VPS_HOST`, `VPS_SUBDOMAIN`, `DATABASE_URL`
    - Verify the deploy workflow references each secret correctly
    - _Requirements: 6.2, 6.4, 6.6_

- [x] 9. Write the rollback script
  - [x] 9.1 Create `/home/deploy/rollback.sh` on the VPS
    - Write the script exactly as specified in the design: `set -euo pipefail`, accepts optional `<commit-hash>` argument (defaults to `HEAD~1`), steps: (a) `git checkout $TARGET_COMMIT`, (b) `pip install --user -r backend/requirements.txt`, (c) `npm ci && npm run build` in `frontend/`, (d) detect migration changes with `git diff --name-only -- backend/alembic_migrations/versions/` and conditionally run `flask db downgrade -1`, (e) `sudo systemctl reload gunicorn`, (f) poll `http://127.0.0.1:5000/api/health` up to 10 times
    - Log rollback actions (timestamp, from-commit, to-commit) to `/home/deploy/rollback.log`
    - Set permissions: `chmod 750 /home/deploy/rollback.sh`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 10. Implement and test the health check endpoint
  - [x] 10.1 Verify or update the `/api/health` endpoint in `backend/app/controllers/routes.py`
    - Confirm the endpoint returns HTTP 200 with a JSON body containing a `status` field when the DB connection succeeds
    - Confirm the endpoint returns HTTP 503 with a JSON body containing a `status` field when the DB connection fails (e.g. `OperationalError`)
    - If the existing implementation does not satisfy these contracts, update it to do so
    - _Requirements: 10.1, 10.2_

  - [x] 10.2 Write example-based unit tests in `backend/tests/test_health_endpoint.py`
    - Test 1: `GET /api/health` with a working DB returns HTTP 200 and `'status' in data`
    - Test 2: `GET /api/health` with DB patched to raise `OperationalError` returns HTTP 503 and `'status' in data`
    - Test 3: `GET /api/health` response body is always valid JSON (never a plain-text error)
    - _Requirements: 10.1, 10.2_

  - [x] 10.3 Write property-based test for health check DB connectivity (Property 1)
    - **Property 1: Health check status reflects database connectivity**
    - **Validates: Requirements 10.1, 10.2**
    - Use `@given(db_available=st.booleans())` with `@settings(max_examples=100)`
    - When `db_available=True`: call `GET /api/health`, assert `status_code == 200` and `'status' in response.get_json()`
    - When `db_available=False`: patch `db.session.execute` to raise `OperationalError`, call `GET /api/health`, assert `status_code == 503` and `'status' in response.get_json()`
    - File: `backend/tests/test_health_properties.py`
    - _Requirements: 10.1, 10.2_

- [x] 11. Checkpoint — run the full backend test suite
  - Run `cd backend && pytest tests/test_health_endpoint.py tests/test_health_properties.py -v` and confirm all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Configure Nginx logging and verify observability
  - [x] 12.1 Confirm Nginx access and error log paths are set correctly
    - Verify `/etc/nginx/sites-available/real-estate` contains `access_log /var/log/nginx/real-estate-access.log` and `error_log /var/log/nginx/real-estate-error.log`
    - Confirm log files are created and written to after a test request
    - _Requirements: 10.4_

  - [x] 12.2 Confirm Gunicorn journal logging is active
    - Verify the gunicorn.service unit file has `StandardOutput=journal` and `StandardError=journal`
    - Confirm `journalctl -u gunicorn -n 5` returns recent log lines
    - _Requirements: 10.3_

- [x] 13. Final checkpoint — end-to-end deployment verification
  - Trigger a push to `main` and confirm the GitHub Actions deploy workflow completes successfully
  - Confirm the post-deploy health check step in the workflow returns HTTP 200
  - Confirm `curl -f https://<subdomain>.duckdns.org/api/health` returns HTTP 200 from a local machine
  - Confirm `curl -I http://<subdomain>.duckdns.org/` returns `301 Moved Permanently`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Property 1 (health check DB connectivity) is the only PBT-applicable property; Property 2 (rollback restores deployable state) is an integration/manual test and is not implemented as a Hypothesis test
- The deploy workflow (`deploy.yml`) depends on the existing `ci.yml` jobs (`frontend`, `backend`) — those job names must match exactly
- The `deploy` user's passwordless sudo is scoped to a single command (`/bin/systemctl reload gunicorn`) to minimize privilege escalation risk
- Old Vite-hashed asset files are intentionally NOT deleted between builds to support in-flight page loads during zero-downtime deploys
- All migration files must follow the idempotent pattern (`IF NOT EXISTS`) per the project migration conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["4.1", "5.1"] },
    { "id": 5, "tasks": ["4.2", "5.2"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2"] },
    { "id": 8, "tasks": ["8.1", "9.1", "10.1"] },
    { "id": 9, "tasks": ["8.2", "10.2"] },
    { "id": 10, "tasks": ["10.3"] },
    { "id": 11, "tasks": ["12.1", "12.2"] }
  ]
}
```
