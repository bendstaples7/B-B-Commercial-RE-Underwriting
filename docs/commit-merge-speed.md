# Commit → push → merge speedups

Local commits and CI no longer both run the full suite. The intended flow:

1. **Local pre-commit** (`.githooks/pre-commit`) — fast always-on guards + staged-path mapped tests. No `npm run build`.
2. **App CI** (`.github/workflows/ci.yml`) — authoritative app checks, path-filtered per tree, aggregated by the **App CI success** job. Ops/backup checks live in **Ops health** and do not gate merges or Deploy.
3. **Human merge** — after `gh pr create`, the agent provides the PR URL and **stops**. The user reviews and merges. Agents must never run `gh pr merge` or enable auto-merge.

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

Require the single check named **App CI success** (not the individual path-filtered jobs, and not Ops health). Skipped jobs are treated as OK by the aggregator.

If branch protection still lists the old name **CI success**, update it to **App CI success** after this workflow rename lands on `main`.

`strict_required_status_checks_policy` is **off** so PRs do not need a rebase onto latest `main` before every merge (that would fight the speedup).

Repository **Allow auto-merge** is **off** (Settings → General → Pull Requests). Leave it off so `gh pr merge --auto` cannot schedule a merge even if an agent is prompted to — a human merges every PR in the GitHub UI.

## Escape hatches

| Command | Effect |
|---------|--------|
| `PRE_COMMIT_FULL=1 git commit ...` | Full backend pytest + frontend `tsc` locally |
| `make pre-pr` / `make pre-pr-quick` | Broader readiness vs `origin/main` |
| `git commit --no-verify` | Skip local hook (CI must still pass) |
