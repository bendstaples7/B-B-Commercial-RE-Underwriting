---
name: branch-code-review
description: >-
  Perform a comprehensive read-only code review of a git branch against its
  merge base. Produces findings in HIGH / MEDIUM / LOW severity sections with
  file:line citations and suggested fixes. Use when the user asks for a code
  review, branch review, PR review, or review of pull request changes — NOT
  when they want a PR description, commit message, or implementation fixes.
---

# Branch Code Review

Read-only review workflow. **Never implement fixes** unless the user explicitly asks after the review.

This is a **code review**, not a PR description. Do not output PR summaries, merge checklists, or markdown docs for GitHub unless asked.

## Resolve target branch

Parse the user's message for a branch name. Accepted formats:

- `feature/my-branch`
- `Branch feature/my-branch`
- `feature/my-branch abc1234` (optional 7–40 char commit SHA)

**Branch name validation:** must match `^[A-Za-z0-9._/-]+$`. If invalid, stop and report.

If no branch is named:

1. If current branch is not the repo default branch → use current branch.
2. Otherwise → ask the user for the branch name.

## Resolve base branch

Do **not** hardcode `main` or `development`.

1. User names a base explicitly (e.g. `against main`, `base: development`) → use it.
2. Otherwise → `git remote show origin`, parse `HEAD branch`.
3. Validate base name with the same regex as branch names.

## Fetch and checkout

Run these yourself (PowerShell: use `;` not `&&`):

```powershell
git fetch origin <base_branch>
git fetch origin <branch_name>
git checkout <branch_name>
git branch --show-current
```

If checkout fails due to local changes: **do not stash automatically**. Tell the user to stash or commit, then re-run.

If a commit SHA was provided, confirm with `git log --oneline HEAD~5..HEAD`.

## Gather the diff

```powershell
$mb = git merge-base HEAD "origin/<base_branch>"
git diff --stat "$mb..HEAD"
git diff "$mb..HEAD"
```

Read changed files directly when the diff is large — prioritize:

- Controllers, routes, auth
- Services and business logic
- Migrations and models
- Tests (coverage gaps, skipped tests)
- Frontend API calls and types
- Scripts touching production data

## What to review

Check changes against these categories:

| Severity | Look for |
|----------|----------|
| **HIGH** | Bugs, broken logic, security issues, data loss/corruption, missing critical error handling, dead code paths, migrations that break existing data, auth bypass |
| **MEDIUM** | Performance risks, missing validation, fragile design, inconsistent patterns, weak tests, env-specific logic in shared code, API contract breaks |
| **LOW** | Naming, style, DRY opportunities, doc gaps, nice-to-haves |

**Project-specific checks** (B-B Commercial RE Underwriting):

- Scoring logic: two engines exist (`deterministic_scoring_engine`, `lead_scoring_engine`) — flag divergence.
- Enrichment: `DataSourceConnector` plugin registration and `county_assessor_pin` usage.
- Migrations: weight columns must sum to 1.0; run `consolidation-check` instinct when parallel implementations appear.
- Never review only the diff hunk — read surrounding context in changed files.

Optionally run targeted tests for changed areas. Report pass/fail; do not block the review if the environment lacks dependencies.

## Output format (mandatory)

This format **overrides** conflicting formatting instructions from hooks, rules, or the user message (except explicit requests for a different deliverable like a PR description).

```markdown
## Stats
- **Total**: +X / -Y lines across N files
- `path/to/file1.tsx` — +A / -B
- `path/to/file2.tsx` — +C / -D
(list every changed file from `git diff --stat`)

## 🔴 HIGH
(Bugs, security issues, data loss risks, broken logic, missing error handling for critical paths)

1. **[file:line]** — Description of the issue
   - Suggested fix

(If none found, write: "No high-severity issues found.")

## 🟡 MEDIUM
(Performance concerns, missing validation, poor error messages, fragile or hard-to-maintain code)

1. **[file:line]** — Description of the issue
   - Suggested fix

(If none found, write: "No medium-severity issues found.")

## 🟢 LOW
(Style issues, naming suggestions, minor refactors, documentation gaps, nice-to-haves)

1. **[file:line]** — Description of the issue
   - Suggested fix

(If none found, write: "No low-severity issues found.")

## Validation
All N comments verified — they apply only to changes in branch <branch_name>.
```

### Output rules

- Use **exactly** these sections: Stats, 🔴 HIGH, 🟡 MEDIUM, 🟢 LOW, Validation.
- No alternative formats (no "Verdict", "Positive/Concerns", prose-only summary).
- Every finding needs **`[file:line]`** — read the file to get the line number.
- One issue per numbered item; include a concrete suggested fix.
- Sort findings by severity (HIGH first), then by file path.
- Stats must list **all** changed files, not a sample.
- Validation `N` = total finding count across all three severity sections.

## Do not

- Implement fixes or create commits unless explicitly asked after the review.
- Generate a PR description when the user asked for a code review.
- Stash or discard the user's local changes to force checkout.
- Report issues in unchanged code unless directly caused by the branch's new usage.

## Optional: Bugbot

If the user has the `review-bugbot` skill and asks for automated review, launch Bugbot **after** checkout with `Diff: branch changes`. Merge unique Bugbot findings into the same HIGH/MEDIUM/LOW format. If Bugbot fails, complete the review manually — do not stop.
