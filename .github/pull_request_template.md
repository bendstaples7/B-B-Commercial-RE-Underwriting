## Deploy / VPS checklist

If this PR changes any of the following, confirm before merge:

- `scripts/deploy.sh`, `scripts/deploy-async-stack-checks.sh`, `scripts/run-vps-readiness-check.sh`
- `scripts/vps-setup/` (sudoers, bootstrap, migrate, Redis, Celery)
- `.github/workflows/deploy.yml` or `.github/workflows/ci.yml` deploy jobs

Checklist:

- [ ] `deploy-contract` CI job passes (sudoers stay in sync with deploy scripts)
- [ ] If deploy infra changed: `vps-readiness` CI passed **or** `migrate-async-stack.sh` was run on the VPS as root
- [ ] If new sudo commands were added: `11-sudoers-deploy.sh` updated and documented in `DEPLOYMENT.md`
