---
name: code-review
description: >-
  Perform a read-only pull-request-style code review with severity-prioritized
  findings and author questions. Use when the user asks for a code review, PR
  review, branch review, or mentions tools like CodeRabbit, Cubic, or CreepCode.
disable-model-invocation: true
---

# Code Review

Review-only workflow. **Do not implement fixes, edit files, commit, or open PRs** unless the user explicitly asks after the review.

## Scope

Determine what to review:

| User intent | Diff source |
|-------------|-------------|
| Default — review my branch | `git diff <base>...HEAD` plus staged/unstaged |
| Uncommitted / dirty working tree only | `git diff` and `git diff --cached` |
| Specific PR or branch | Check out that branch first, then branch diff |
| Specific files | Read those files and their call sites |

**Base branch:** infer the repo default (`main`, `master`, etc.) via `git symbolic-ref refs/remotes/origin/HEAD` or `git branch -r`. When the user names a PR URL or number, fetch the PR's actual target branch first (`gh pr view <n> --json baseRefName`) and use that as `<base>` — do not assume `main`.

If the user names a PR URL, number, or branch, ensure that branch is checked out locally before reviewing. If checkout is blocked by local changes, explain and ask before stashing.

## Review workflow

1. **Gather context**
   - Resolve `<base>` (see above).
   - Run `git log --oneline <base>...HEAD` for commit narrative.
   - Run `git diff --stat <base>...HEAD` for branch changes; also run `git diff --stat` and `git diff --stat --cached` when staged/unstaged changes must be included.
   - Read the full diff (`git diff <base>...HEAD`, plus `git diff` / `git diff --cached` when applicable) for changed files.
   - Read each changed file plus immediate callers/callees when behavior is unclear.

2. **Load project standards** (when present — skip silently if missing)
   - `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`, `.cursor/rules/`, project skills
   - Test patterns, naming, and "one writer per column / one route per URL" style rules

3. **Analyze the change holistically**
   - What problem does this solve? Does the approach fit existing patterns?
   - What could break in production? What's untested or untestable?

4. **Write the review** using the output template below.

5. **Stop.** Do not fix findings unless the user asks in a follow-up.

## Review dimensions

Cover every dimension that applies; skip only when clearly irrelevant.

- **Correctness** — logic bugs, race conditions, off-by-one, null/undefined handling, error paths
- **Security** — authz/authn gaps, injection, secrets, unsafe deserialization, data exposure
- **Data & migrations** — schema changes, backfills, rollback, dual-write risks
- **API & contracts** — breaking changes, versioning, validation, idempotency
- **Performance** — N+1 queries, unbounded loops, missing indexes, hot-path allocations
- **Reliability** — retries, timeouts, partial failure, observability
- **Testing** — coverage of new behavior, flaky patterns, missing edge cases
- **Maintainability** — naming, duplication, dead code, complexity, parallel implementations
- **UX / accessibility** — loading/error states, a11y, confusing copy (frontend changes)

## Severity rubric

Assign exactly one severity per finding.

| Severity | When to use |
|----------|-------------|
| **High** | Likely bug, security issue, data loss/corruption, broken contract, or production outage risk. Should block merge until resolved or explicitly accepted. |
| **Medium** | Real issue that may cause bugs, tech debt, or maintenance pain under common conditions. Should be addressed or tracked before merge when practical. |
| **Low** | Style, minor clarity, optional simplification, or nit. Safe to merge; author decides. |

Do not inflate severity. Do not file drive-by nits as High. Prefer fewer, sharper findings over noise.

## Finding quality bar

Each finding must include:

- **Location** — `path/to/file:line` (best effort; use a line range when helpful)
- **Issue** — what is wrong or risky, in plain language
- **Why it matters** — user impact, failure mode, or maintenance cost
- **Suggestion** — concrete fix direction (pseudocode or approach OK; do not implement)

Skip praise-only comments unless summarizing in **Summary**. Do not repeat the same root cause in multiple findings — merge related items.

## Questions for the author

Ask questions when:

- Intent is ambiguous from the diff alone
- A tradeoff was made without explanation (performance vs simplicity, etc.)
- Test gaps make behavior unclear
- Migration/rollout or feature-flag strategy is missing
- You need confirmation that an edge case was considered

Frame as genuine questions, not disguised demands. Number them (`Q1`, `Q2`, …).

## Output template

Use this structure exactly:

```markdown
# Code Review — <branch or short title>

## Summary
<2–4 sentences: what changed, overall quality assessment, merge recommendation>

**Recommendation:** Approve | Approve with nits | Request changes

## Stats
- Files reviewed: N
- Findings: H high · M medium · L low
- Questions: Q

---

## High severity
<!-- Omit section if none -->
### H1 — <short title>
- **Location:** `path/file.ext:42`
- **Issue:** …
- **Why it matters:** …
- **Suggestion:** …

---

## Medium severity
<!-- Omit section if none -->

---

## Low severity
<!-- Omit section if none -->

---

## Questions for the author
<!-- Omit section if none -->
1. **Q1 — <topic>:** …
2. **Q2 — <topic>:** …

---

## Positive notes
<!-- Optional: 0–3 bullets on well-done aspects — keep brief -->
```

## Hard rules

- **Read-only:** no file edits, no `git commit`, no auto-fix PRs.
- **No scope creep:** review the diff; do not refactor unrelated code.
- **Be specific:** cite lines and symbols; avoid vague "consider improving error handling."
- **Respect existing conventions:** match the codebase's patterns unless they are clearly harmful.
- **Empty diff:** if there is nothing to review, say so in one sentence and stop.

## After the review

Wait for the user. If they ask to fix findings, switch to implementation mode explicitly — the review skill no longer applies.
