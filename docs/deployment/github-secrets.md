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
postgresql://app_user:<password>@<VPS_IP>:5432/real_estate_analysis
```

**Example:**

```
postgresql://app_user:s3cur3p4ss@65.21.123.45:5432/real_estate_analysis
```

> **Note:** Use the VPS public IP here (same value as `VPS_HOST`), not `localhost`.
> The migration command runs on the GitHub Actions runner, which connects to the
> VPS over the network — `localhost` would refer to the runner itself.

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

## Workflow Secret Reference Summary

| Secret | Workflow Step | How Referenced |
|--------|--------------|----------------|
| `VPS_SSH_KEY` | Load SSH key | `${{ secrets.VPS_SSH_KEY }}` |
| `VPS_HOST` | Add VPS to known hosts | `${{ secrets.VPS_HOST }}` |
| `VPS_USER` | Deploy | `${{ secrets.VPS_USER }}` |
| `VPS_HOST` | Deploy | `${{ secrets.VPS_HOST }}` |
| `DATABASE_URL` | Deploy | `${{ secrets.DATABASE_URL }}` |
| `VPS_SUBDOMAIN` | Post-deploy health check | `${{ secrets.VPS_SUBDOMAIN }}` |

All secrets are passed via `${{ secrets.SECRET_NAME }}` syntax — no secret values
are hardcoded anywhere in the workflow YAML.

---

## Security Notes

- Never commit secret values to the repository. The `.env` file is already in
  `.gitignore`.
- The SSH private key grants shell access to the VPS as the `deploy` user. Treat
  it with the same care as a password.
- The `deploy` user's sudo access is intentionally scoped to a single command
  (`/bin/systemctl reload gunicorn`) to minimize privilege escalation risk.
- Rotate the `DATABASE_URL` password if you suspect it has been compromised. Update
  both the GitHub secret and the `/home/deploy/app/backend/.env` file on the VPS.
