# Branch Hygiene Rules

## CRITICAL: Always check for missing commits before starting work

Before starting any task on a feature branch, run:

```
git fetch origin main
git log HEAD..origin/main --oneline
```

If this shows any commits, those commits are on `main` but NOT on the current branch.
**You must merge them before writing any code:**

```
git merge origin/main
```

Failure to do this causes regressions where features that exist on main are silently
missing from the working branch — exactly what happened with the address autocomplete
(commits c477124, 716bdf5, bd4f510 were on feature/multifamily-underwriting-proforma
but never merged to main, so the current branch never got them).

## Rule: Never declare a feature "working" without verifying the branch is current

Before any "this is working" declaration:
1. Run `git fetch origin main && git log HEAD..origin/main --oneline`
2. If output is non-empty, merge main first, then re-verify
3. Only declare working after the branch is current AND tests pass

## Rule: After every PR merge, check sibling branches for stranded commits

When a PR is merged, check if the source branch had any commits made AFTER the PR
was opened that weren't included in the merge. These commits are stranded and must
be cherry-picked or re-applied manually.

Pattern that causes regressions:
1. Branch A opened as PR
2. More commits added to Branch A after PR opened
3. PR merged (only includes commits up to when PR was opened)
4. New branch B created from main — missing the post-PR commits from Branch A
5. Features from those commits silently disappear

## Rule: `npm install` after any branch switch or merge

After merging main or switching branches, always run `npm install` in `frontend/`
to ensure package.json dependencies are installed. Missing packages cause silent
failures (TypeScript compiles but runtime crashes).
