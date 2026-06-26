# Architecture Review — Feature Proposal

> **Template version:** 1.0  
> **Purpose:** Mandatory pre-implementation review for all features, especially UI components.

---

## Feature Overview

- **Feature name:**
- **Feature owner:**
- **Target release:**
- **Related cards/ACs:**

---

## Problem Statement

_What problem does this feature solve? Why is it needed?_

---

## Proposed Solution

_High-level technical approach._

---

## Navigation Impact ⚠️ (MANDATORY)

_Every UI feature MUST complete this section. If no navigation changes are involved, state "No navigation changes" and explain why._

- **New route(s) added:** (list route paths, e.g. `/deals/:id/enrichment`)
- **Route path(s):** (full URL patterns)
- **Navigation entry location:** (sidebar, avatar menu, sub-page, modal, top nav, breadcrumb, etc.)
- **Navigation entry label:** (the exact text users see/click)
- **How user reaches this feature (step by step):**
  1. _(e.g. Click "Deals" in the sidebar)_
  2. _(e.g. Select a deal from the list)_
  3. _(e.g. Click the "Enrichment" tab)_
- **Back navigation:** (what happens when the user goes back — where do they land?)
- **Access control / visibility rules:** (who can see this route — role, permission, feature flag?)

---

## Data Model Changes

- **New tables/collections:**
- **Modified schemas:**
- **Migrations required:**

---

## API / Backend Changes

- **New endpoints:**
- **Modified endpoints:**
- **Payload changes:**

---

## Dependencies

- **Internal dependencies:**
- **External dependencies / third-party:**

---

## Testing Strategy

- **Unit tests:**
- **Integration tests:**
- **E2E / navigation tests:**

---

## Rollout & Rollback

- **Feature flag:** (name, default state)
- **Rollback plan:**
- **Monitoring / alerts:**

---

## Review Checklist

- [ ] Navigation Impact section is complete (or explicitly marked as "No navigation changes" with justification)
- [ ] Routes are registered in the router config
- [ ] Navigation sidebar/menu entries are documented
- [ ] Feature manifest will be generated (run `scripts/create-feature-manifest.sh`)
- [ ] UI card ACs include navigation criteria
- [ ] Acceptance criteria are verifiable in a review environment