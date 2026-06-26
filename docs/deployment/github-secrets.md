# GitHub Repository Secrets for VPS Deployment

The GitHub Actions deploy workflow (`.github/workflows/deploy.yml`) requires five
repository secrets to be configured before the workflow can run successfully.

## How to Add Secrets

1. Go to your GitHub repository page
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Enter the secret name and value, then click **Add secret**
5. Repeat for each secret below

---

## Required Secrets

### `VPS_SSH_KEY`

**What it is:** The private SSH key used by GitHub Actions to authenticate as the
`deploy` user on the VPS.

**How to generate:**

```bash
ssh-keygen -t ed25519 -C "deploy@bbanalyzer" -f ~/.ssh/bbanalyzer_deploy
```

This creates two files:
- `~/.ssh/bbanalyzer_deploy` — the **private key** (this is the secret value)
- `~/.ssh/bbanalyzer_deploy.pub` — the public key (add this to the VPS)

**Adding the public key to the VPS:**

```bash
# On the VPS, as root or the deploy user:
cat ~/.ssh/bbanalyzer_deploy.pub >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
```

**Secret value:** The full contents of `~/.ssh/bbanalyzer_deploy`, including the
`-----BEGIN OPENSSH PRIVATE KEY-----` header and `-----END OPENSSH PRIVATE KEY-----`
footer.

**Used in workflow:** `webfactory/ssh-agent@v0.9.0` step — loads the key into the
SSH agent for the duration of the job.

---

### `VPS_USER`

**What it is:** The username of the deploy account on the VPS.

**Value:** `deploy`

**Used in workflow:** The `Deploy` step connects via `ssh $VPS_USER@$VPS_HOST`.

---

### `VPS_HOST`

**What it is:** The public IP address of the Hetzner VPS.

**How to find it:** Log in to the [Hetzner Cloud Console](https://console.hetzner.cloud),
select your server, and copy the IPv4 address shown on the server overview page.

**Example value:** `65.21.123.45`

**Used in workflow:**
- `ssh-keyscan -H ${{ secrets.VPS_HOST }}` — adds the VPS to known hosts to
  prevent host key verification prompts
- The `Deploy` step env — used to form the SSH connection string

---

### `VPS_SUBDOMAIN`

**What it is:** The DuckDNS subdomain prefix (the part before `.duckdns.org`).

**Example:** If your site is `bbanalyzer.duckdns.org`, the value is `bbanalyzer`.

**How to find it:** Log in to [duckdns.org](https://www.duckdns.org) and check
the subdomain you registered for this project.

**Used in workflow:** The post-deploy health check polls
`https://${VPS_SUBDOMAIN}.duckdns.org/api/health` to confirm the deployment
succeeded.

---

### `DATABASE_URL`

**What it is:** The PostgreSQL connection string used by `flask db upgrade head`
during deployment to run any pending Alembic migrations against the production
database.

**Format:**

```
postgresql://app_user:<password>@localhost:5432/real_estate_analysis
```

**Example:**

```
postgresql://app_user:s3cur3p4ss@localhost:5432/real_estate_analysis
```

> **Note:** The migration command runs on the VPS over SSH, so use `localhost` as
> the host — not the VPS public IP. The `flask db upgrade head` command executes
> directly on the VPS where PostgreSQL is running, so `localhost` correctly refers
> to the VPS's own database.

**How to find the password:** This is the password you set for the `app_user`
PostgreSQL role during initial VPS setup (Task 2.1). If you need to reset it:

```bash
# On the VPS as postgres superuser:
psql -U postgres -c "ALTER ROLE app_user WITH PASSWORD 'new-password';"
```

**Used in workflow:** The `Deploy` step injects `DATABASE_URL` into the SSH
session so the migration command can connect:

```bash
FLASK_ENV=production DATABASE_URL="${DATABASE_URL}" flask db upgrade head
```

---

### `B2_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME` (optional)

**What they are:** Backblaze B2 credentials for off-site database backup uploads.
When all three are set, the deploy workflow configures `rclone` on the VPS and
enables `REMOTE_METHOD=rclone` in `/home/deploy/backup.conf`.

**How to obtain:**

1. Sign up at [backblaze.com/b2](https://www.backblaze.com/b2-cloud-storage.html)
2. Create a **private** bucket (e.g. `bbanalyzer-db-backups`)
3. Under **Application Keys**, create a key scoped to that bucket (read + write)
4. Set GitHub secrets:
   - `B2_KEY_ID` — the key ID (`004…`)
   - `B2_APPLICATION_KEY` — the secret key
   - `B2_BUCKET_NAME` — bucket name only (not a path)

**Cost:** At current production dump size (~57 MB), steady-state cloud storage is
~5 GB with 30-day retention — **$0/month** on B2’s permanent 10 GB free tier.

**Used in workflow:** Deploy step runs `setup-b2-rclone.py` and
`inject-remote-backup.py` after copying backup scripts to the VPS.

---

### `VPS_HOST_KEY`

**What it is:** The VPS SSH host public key line for `known_hosts`, preventing
MITM prompts during CI SSH connections.

**How to obtain:**

```bash
ssh-keyscan -H <VPS_IP>
```

**Used in workflow:** Added to `~/.ssh/known_hosts` before deploy and VPS readiness
checks.

---

### `VPS_ROOT_SSH_KEY` (optional)

**What it is:** Private SSH key for `root@VPS_HOST`. When set, the deploy workflow
can automatically run `scripts/vps-setup/migrate-async-stack.sh` if the async stack
(Redis/Celery/sudoers) is not yet provisioned.

**When to set:** Recommended after PR #57+ so first async-stack deploy does not
require manual root SSH.

**Security:** Grants root access. Use a dedicated deploy automation key and
restrict to the VPS IP in `sshd_config` if possible.

---

## Workflow Secret Reference Summary

| Secret | Workflow Step | How Referenced |
|--------|--------------|----------------|
| `VPS_SSH_KEY` | Deploy / CI VPS checks | `${{ secrets.VPS_SSH_KEY }}` |
| `VPS_HOST_KEY` | Deploy / CI VPS checks | `${{ secrets.VPS_HOST_KEY }}` |
| `VPS_USER` | Deploy | `${{ secrets.VPS_USER }}` |
| `VPS_HOST` | Deploy | `${{ secrets.VPS_HOST }}` |
| `DATABASE_URL` | Deploy | `${{ secrets.DATABASE_URL }}` |
| `B2_KEY_ID` | Deploy (optional) | `${{ secrets.B2_KEY_ID }}` |
| `B2_APPLICATION_KEY` | Deploy (optional) | `${{ secrets.B2_APPLICATION_KEY }}` |
| `B2_BUCKET_NAME` | Deploy (optional) | `${{ secrets.B2_BUCKET_NAME }}` |
| `VPS_SUBDOMAIN` | Post-deploy health check | `${{ secrets.VPS_SUBDOMAIN }}` |
| `VPS_ROOT_SSH_KEY` | Optional auto-migrate | `${{ secrets.VPS_ROOT_SSH_KEY }}` |

All secrets are passed via `${{ secrets.SECRET_NAME }}` syntax — no secret values
are hardcoded anywhere in the workflow YAML.

---

## Security Notes

- Never commit secret values to the repository. The `.env` file is already in
  `.gitignore`.
- The SSH private key grants shell access to the VPS as the `deploy` user. Treat
  it with the same care as a password.
- The `deploy` user's sudo access is scoped to specific `systemctl` commands and
  `/usr/local/sbin/bootstrap-async-stack` — see `scripts/vps-setup/11-sudoers-deploy.sh`.
- Rotate the `DATABASE_URL` password if you suspect it has been compromised. Update
  both the GitHub secret and the `/home/deploy/app/backend/.env` file on the VPS.
