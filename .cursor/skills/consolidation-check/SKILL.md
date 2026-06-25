---
name: consolidation-check
description: Search for duplicate implementations before adding components, services, routes, or scoring logic. Use when creating new UI, API endpoints, services, queue pages, forms, or migration work; or when the user asks to avoid duplication or check canonical sources.
---

# Consolidation Check

Run this **before writing code** when adding or replacing functionality.

## Steps

1. Read [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) canonical table.
2. Search the codebase:
   - Component/service class name
   - Route path (`@*.route`, `Route path=`)
   - DB column writers (`lead.lead_score =`, `recommended_action =`)
3. If overlap exists, choose **extend canonical** or **replace + delete** — never parallel.
4. Output a **Consolidation Decision** block (required):

```markdown
## Consolidation Decision
- **Domain:** (e.g. activity logging)
- **Canonical:** path/to/file
- **Action:** extend | replace+delete
- **Delete in this PR:** (files, or "none")
- **Extract shared helper:** (or "none")
- **Justification:** (one sentence if new file is truly needed)
```

5. Implement only after the decision is stated.

## Red flags (stop and consolidate)

- Second component for the same user-facing screen
- Same Flask URL on two blueprints
- Copy-pasted decorator, formatter, or dialog
- `*V2`, `New*`, `Unified*` next to an existing implementation
- Stub/re-export without a deletion ticket in the same PR

## Validation

After changes, run:

```bash
python scripts/check_duplication.py
```

Fix any failures before considering the task complete.
