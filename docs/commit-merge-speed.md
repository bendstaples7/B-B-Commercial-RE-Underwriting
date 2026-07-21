# Commit → push → merge speedups

Local commits and CI no longer both run the full suite. The intended flow:

1. **Local pre-commit** (`.githooks/pre-commit`) — fast always-on guards + staged-path mapped tests. No `npm run build`.
2. **CI** (`.github/workflows/ci.yml`) — authoritative full checks, path-filtered per tree, aggregated by the **CI success** job.
3. **Auto-merge** — after `gh pr create`, run `gh pr merge --auto --squash` so a green **CI success** check merges without waiting on a human click.

## Install hooks

**Windows (PowerShell):**

```powershell
powershell -File scripts/install-git-hooks.ps1
```

**macOS / Linux / Git Bash:**

```bash
make hooks
# or: bash scripts/install-git-hooks.sh
```

Sets `core.hooksPath=.githooks` for this clone.

## Branch protection

Require the single check named **CI success** (not the individual path-filtered jobs). Skipped jobs are treated as OK by the aggregator.

`strict_required_status_checks_policy` is **off** so PRs do not need a rebase onto latest `main` before every merge (that would fight the speedup). Auto-merge still waits for **CI success**.

Human gate: approve **opening/shipping** the PR (see agent rules). GitHub approval count remains 0; do not treat auto-merge as a substitute for that product review.

## Escape hatches

| Command | Effect |
|---------|--------|
| `PRE_COMMIT_FULL=1 git commit ...` | Full backend pytest + frontend `tsc` locally |
| `make pre-pr` / `make pre-pr-quick` | Broader readiness vs `origin/main` |
| `git commit --no-verify` | Skip local hook (CI must still pass) |
