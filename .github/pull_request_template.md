## Summary

<!-- 1-3 bullet points: what changed and why -->

## Test plan

- [ ] <!-- how you verified -->

## Consolidation checklist

- [ ] Searched for existing implementation; extended canonical source ([docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md))
- [ ] No parallel routes, services, or components introduced
- [ ] If this replaces something: legacy code deleted (not left alongside redirect)
- [ ] No new per-file copies of shared infra (`handle_errors`, `formatDate`, etc.)
- [ ] `python scripts/check_duplication.py` passes
- [ ] Enable auto-merge after create: `gh pr merge --auto --squash` (required check: **CI success**)
