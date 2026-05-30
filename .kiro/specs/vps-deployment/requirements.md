# Requirements Document

## Introduction

Deploy the existing Flask + React real estate analysis application to a Hetzner CX22 VPS (~$4.50/month) so a 3-person team can access it at a real URL. The deployment must be automated via GitHub Actions CI/CD, use a free DuckDNS subdomain with Let's Encrypt SSL, migrate existing Neon PostgreSQL data to a local VPS Postgres instance, and be robust enough that pushes to `main` deploy without manual intervention. Celery and Redis are explicitly excluded from the initial deployment (USE_ASYNC_COMPARABLE_SEARCH=false).

## Glossary

- **VPS**: Virtual Private Server — the Hetzner CX22 Ubuntu machine that hosts the application.
- **Gunicorn**: Python WSGI HTTP server that runs the Flask application in production.
- **Nginx**: Reverse proxy that terminates HTTPS, serves the React static build, and forwards `/api` requests to Gunicorn.
- **DuckDNS**: Free dynamic DNS service that provides a `*.duckdns.org` subdomain pointing to the VPS IP.
- **Certbot**: Let's Encrypt ACME client that provisions and auto-renews free TLS certificates.
- **Systemd_Service**: A Linux systemd unit that manages the Gunicorn process (start, stop, restart, auto-restart on failure).
- **GitHub_Actions**: CI/CD platform that runs tests and deploys to the VPS on every push to `main`.
- **Deploy_User**: A non-root Linux user (`deploy`) created on the VPS that owns the application files and runs Gunicorn.
- **pg_dump / pg_restore**: PostgreSQL utilities used to export data from Neon and import it into the VPS Postgres instance.
- **Alembic**: Database migration tool (via Flask-Migrate) that keeps the schema in sync with the application code.
- **Zero-Downtime_Deploy**: A deployment strategy where the old Gunicorn process continues serving requests until the new code is fully loaded and ready.
- **Rollback**: Reverting the application to the previously deployed Git commit when a deployment introduces a regression.
- **Hardening**: Security configuration applied to the VPS to reduce the attack surface (firewall, SSH key-only auth, non-root user).
- **Environment_File**: A `.env` file stored on the VPS at `/home/deploy/app/backend/.env` containing all production secrets and configuration.

---

## Requirements

### Requirement 1: VPS Provisioning and Hardening

**User Story:** As a team member, I want the VPS to be securely configured from the start, so that the application is not exposed to trivial attacks and the team can SSH in safely.

#### Acceptance Criteria

1. THE VPS SHALL run Ubuntu 22.04 LTS on a Hetzner CX22 instance (2 vCPU, 4 GB RAM, 40 GB SSD), independent of any other security configuration steps.
2. WHEN the VPS is first provisioned, THE Deploy_User SHALL be created as a non-root user with `sudo` privileges.
3. THE VPS SHALL accept SSH connections only via public-key authentication; password authentication SHALL be disabled in `/etc/ssh/sshd_config`.
4. THE VPS SHALL run UFW firewall with only ports 22 (SSH), 80 (HTTP), and 443 (HTTPS) open; all other inbound ports SHALL be denied by default.
5. THE VPS SHALL have `fail2ban` installed and configured to ban IPs after 5 failed SSH login attempts within 10 minutes.
6. WHEN the VPS is provisioned, THE VPS SHALL have Python 3.11, Node.js 20, PostgreSQL 15, Nginx, and Certbot all successfully installed via the system package manager before provisioning is considered complete; IF any single package installation fails, THEN THE provisioning process SHALL be considered incomplete.
7. THE Deploy_User SHALL own the application directory at `/home/deploy/app` and all files within it.

---

### Requirement 2: PostgreSQL Setup and Data Migration

**User Story:** As a team member, I want all existing users and leads from the Neon database to be available on the VPS, so that no data is lost during the migration.

#### Acceptance Criteria

1. THE VPS SHALL run a local PostgreSQL 15 instance with a dedicated database named `real_estate_analysis`.
2. THE VPS SHALL have a dedicated PostgreSQL role named `app_user` with `LOGIN`, `CREATEDB` (for Alembic), and DML privileges (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) on the `real_estate_analysis` database; the role SHALL NOT have superuser privileges.
3. WHEN migrating data from Neon, THE Deploy_User SHALL use `pg_dump` with `--no-owner --no-acl` flags to export the Neon database to a `.dump` file.
4. WHEN restoring data to the VPS, THE Deploy_User SHALL use `pg_restore` to load the dump into the local `real_estate_analysis` database.
5. AFTER the restore completes, THE Deploy_User SHALL run `flask db upgrade head` to apply any pending Alembic migrations and ensure the schema is at the current head revision.
6. IF the `pg_restore` command exits with a non-zero status, THEN THE Deploy_User SHALL inspect the error output before proceeding; non-fatal errors (e.g. duplicate objects from `IF NOT EXISTS` migrations) SHALL be documented as acceptable.
7. THE `app_user` PostgreSQL role SHALL be the owner of all tables in the `real_estate_analysis` database after migration.

---

### Requirement 3: Flask/Gunicorn Application Service

**User Story:** As a team member, I want the Flask backend to run reliably as a managed service, so that it restarts automatically on failure and survives VPS reboots.

#### Acceptance Criteria

1. THE Systemd_Service SHALL be defined at `/etc/systemd/system/gunicorn.service` and manage the Gunicorn process.
2. THE Systemd_Service SHALL run Gunicorn with 3 worker processes using the `sync` worker class, binding to `127.0.0.1:5000`.
3. THE Systemd_Service SHALL set `Restart=on-failure` and `RestartSec=5s` so Gunicorn restarts automatically within 5 seconds of an unexpected exit.
4. THE Systemd_Service SHALL load environment variables from `/home/deploy/app/backend/.env` via the `EnvironmentFile` directive.
5. THE Systemd_Service SHALL run as the `deploy` user and group.
6. WHEN the VPS reboots, THE Systemd_Service SHALL start automatically because it is enabled via `systemctl enable gunicorn`.
7. THE Systemd_Service SHALL set `FLASK_ENV=production` so the application runs with production thresholds (`MIN_COMPARABLES=10`, `MIN_VALUATION_COMPARABLES=5`) and does not auto-apply migrations on startup.
8. THE Environment_File on the VPS SHALL contain all required variables: `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY`, `FLASK_ENV=production`, `USE_ASYNC_COMPARABLE_SEARCH=false`, and all external API keys used by the application.

---

### Requirement 4: Frontend Build and Nginx Static File Serving

**User Story:** As a team member, I want the React frontend to be served as optimized static files, so that page loads are fast and the backend is not burdened with serving assets.

#### Acceptance Criteria

1. THE Deploy_User SHALL build the React frontend by running `npm ci && npm run build` in the `frontend/` directory, producing static files in `frontend/dist/`.
2. Nginx SHALL serve the React static files from `/home/deploy/app/frontend/dist` for all non-`/api` requests.
3. WHEN a request path does not match a static file, Nginx SHALL serve `index.html` from the dist directory so that React Router client-side routing works correctly.
4. Nginx SHALL proxy all requests matching `/api/*` to `http://127.0.0.1:5000` (Gunicorn) with appropriate `proxy_set_header` directives (`Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`).
5. Nginx SHALL set a `Cache-Control: max-age=31536000, immutable` header for all files under `/assets/` (Vite-hashed filenames) and `Cache-Control: no-cache` for `index.html`.
6. THE Nginx configuration SHALL be placed at `/etc/nginx/sites-available/real-estate` and symlinked to `/etc/nginx/sites-enabled/real-estate`; the default Nginx site SHALL be disabled.
7. WHEN the Nginx configuration is updated, THE Deploy_User SHALL run `nginx -t` to validate the configuration before reloading Nginx.

---

### Requirement 5: DuckDNS Subdomain and Let's Encrypt SSL

**User Story:** As a team member, I want the application accessible at a real HTTPS URL, so that the browser does not show security warnings and the team can bookmark a stable address.

#### Acceptance Criteria

1. THE VPS SHALL be reachable at a DuckDNS subdomain (e.g. `bbanalyzer.duckdns.org`) by registering the subdomain at duckdns.org and pointing it to the VPS public IP.
2. THE VPS SHALL have a cron job or systemd timer that runs the DuckDNS update script every 5 minutes to keep the DNS record current if the VPS IP changes.
3. THE VPS SHALL have a valid Let's Encrypt TLS certificate for the DuckDNS subdomain, obtained via `certbot --nginx`.
4. WHEN the Let's Encrypt certificate is within 30 days of expiry, Certbot SHALL automatically renew it via the `certbot.timer` systemd timer (installed by the `certbot` package).
5. Nginx SHALL redirect all HTTP (port 80) requests to HTTPS (port 443) with a 301 permanent redirect.
6. THE Nginx TLS configuration SHALL use a minimum TLS version of 1.2 and the `ssl_ciphers` recommended by the Mozilla Intermediate compatibility profile.

---

### Requirement 6: GitHub Actions CI/CD Pipeline

**User Story:** As a developer, I want every push to `main` to automatically deploy to the VPS after tests pass, so that the team always has the latest working version without manual steps.

#### Acceptance Criteria

1. THE GitHub_Actions deploy workflow SHALL trigger on every push to the `main` branch after the existing CI job (frontend typecheck, build, tests; backend pytest) passes successfully.
2. THE GitHub_Actions deploy workflow SHALL connect to the VPS via SSH using a private key stored as a GitHub Actions secret (`VPS_SSH_KEY`) and the deploy user's username (`VPS_USER`) and host (`VPS_HOST`).
3. WHEN deploying, THE GitHub_Actions workflow SHALL execute these steps in order on the VPS: (a) `git pull origin main`, (b) `pip install -r backend/requirements.txt`, (c) `npm ci && npm run build` in `frontend/`, (d) `flask db upgrade head`, (e) reload Gunicorn via `systemctl reload gunicorn`; ALL steps MUST succeed for the deployment to be considered complete, and IF any step fails, THE workflow SHALL halt immediately without proceeding to subsequent steps.
4. THE GitHub_Actions workflow SHALL set `FLASK_ENV=production` and `DATABASE_URL` from GitHub Actions secrets when running `flask db upgrade head` during deployment.
5. IF any deployment step fails, THE GitHub_Actions workflow SHALL exit with a non-zero status so the failure is visible in the GitHub Actions UI and does not silently leave the VPS in a broken state.
6. THE GitHub_Actions workflow SHALL NOT store secrets in the workflow YAML file; all secrets SHALL be stored in GitHub repository secrets and referenced via `${{ secrets.SECRET_NAME }}`.
7. THE GitHub_Actions workflow file SHALL be stored at `.github/workflows/deploy.yml`, separate from the existing `.github/workflows/ci.yml`.

---

### Requirement 7: Environment Variable Management

**User Story:** As a developer, I want secrets managed securely and consistently between local development and production, so that credentials are never committed to the repository.

#### Acceptance Criteria

1. THE Environment_File at `/home/deploy/app/backend/.env` SHALL NOT be committed to the Git repository; it SHALL be listed in `.gitignore`.
2. THE Environment_File SHALL be created manually on the VPS during initial setup by copying `backend/.env.example` and filling in production values.
3. WHEN the application starts in production, THE Flask application SHALL read all configuration from environment variables loaded from the Environment_File via `python-dotenv`.
4. THE GitHub_Actions workflow SHALL use GitHub repository secrets for all values needed during deployment (SSH key, VPS host, VPS user, DATABASE_URL for migrations).
5. IF a required environment variable is missing from the Environment_File, THEN THE Flask application SHALL log a descriptive error message identifying the missing variable name to stderr before exiting; the error message SHALL always be emitted as a separate action from the exit so that it is visible in the systemd journal even if the exit itself fails.
6. THE `backend/.env.example` file SHALL be kept up to date with all variables required for production deployment, with placeholder values and comments explaining each variable.

---

### Requirement 8: Zero-Downtime Deployment Strategy

**User Story:** As a team member, I want deployments to not interrupt active sessions, so that a push to `main` during working hours does not kick anyone out of the application.

#### Acceptance Criteria

1. WHEN a deployment is triggered, THE GitHub_Actions workflow SHALL send a `SIGHUP` signal to the Gunicorn master process (via `systemctl reload gunicorn`) rather than a full `systemctl restart`, so that Gunicorn performs a graceful worker reload.
2. WHEN Gunicorn receives `SIGHUP`, THE Gunicorn master process SHALL spawn new workers with the updated code before terminating old workers; at least one worker SHALL remain available to serve requests throughout the entire transition period; IF new workers fail to start during the reload, THE reload process SHALL continue and external monitoring (the post-deploy health check) SHALL detect and surface the failure.
3. THE Gunicorn configuration SHALL set `--timeout 120` so long-running requests (e.g. comparable search) are not killed mid-flight during a reload.
4. THE Nginx configuration SHALL set `proxy_read_timeout 120s` and `proxy_connect_timeout 10s` to match the Gunicorn timeout.
5. WHEN the frontend build produces new hashed asset filenames, THE old static files SHALL remain on disk until the next deployment so that any in-flight page loads referencing old asset URLs do not 404.

---

### Requirement 9: Rollback Strategy

**User Story:** As a developer, I want a documented and tested rollback procedure, so that if a deployment breaks the application I can restore the previous working version within minutes.

#### Acceptance Criteria

1. THE deployment process SHALL preserve the ability to roll back by keeping the full Git history on the VPS; rollback SHALL be achievable by running `git checkout <previous-commit>` followed by a re-deploy sequence.
2. WHEN a rollback is needed, THE Deploy_User SHALL execute a rollback script that performs ALL of the following steps: (a) checks out the previous Git commit, (b) reinstalls Python dependencies, (c) rebuilds the frontend, (d) runs `flask db downgrade -1` if the failing deployment included a schema migration, and (e) reloads Gunicorn; ALL steps MUST complete for the rollback to be considered successful.
3. THE rollback script SHALL be stored at `/home/deploy/rollback.sh` on the VPS and SHALL be executable by the `deploy` user.
4. IF a database migration was applied as part of the failing deployment, THEN THE rollback script SHALL run `flask db downgrade -1` before reloading Gunicorn to restore the previous schema state.
5. THE rollback script SHALL log the rollback action (timestamp, commit hash rolled back from, commit hash rolled back to) to `/home/deploy/rollback.log`.

---

### Requirement 10: Observability and Health Checks

**User Story:** As a team member, I want basic visibility into whether the application is running correctly, so that I can detect problems before users report them.

#### Acceptance Criteria

1. THE Flask application SHALL expose a `/api/health` endpoint that returns HTTP 200 with a JSON body `{"status": "ok"}` when the application and database connection are healthy.
2. WHEN the database connection is unavailable, THE `/api/health` endpoint SHALL return HTTP 503 with a JSON body `{"status": "error", "detail": "<reason>"}`.
3. THE Systemd_Service SHALL write Gunicorn stdout and stderr to the systemd journal, accessible via `journalctl -u gunicorn -f`.
4. THE Nginx access log SHALL be written to `/var/log/nginx/real-estate-access.log` and the error log to `/var/log/nginx/real-estate-error.log`.
5. THE GitHub_Actions deploy workflow SHALL include a post-deploy health check step that calls `curl -f https://<subdomain>.duckdns.org/api/health`; IF the endpoint does not return HTTP 200 within 30 seconds of the Gunicorn reload, THE health check step SHALL fail with a non-zero exit code, causing the entire workflow to be marked as failed.
