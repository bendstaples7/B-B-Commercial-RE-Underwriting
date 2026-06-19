# HubSpot Sync Bugs — Bugfix Design

## Overview

Three interconnected bugs in the HubSpot sync pipeline prevent CRM data from surfacing
correctly. All three share a common upstream cause: timing and ordering dependencies
between the matching, enrichment, and activity-conversion pipeline steps.

**Bug 1 — Deal stage not syncing**: `enrich_lead_from_deal` in
`hubspot_matcher_service.py` already translates stage IDs via `stage_label_map`, and
`run_enrich_leads_from_hubspot` in `hubspot_tasks.py` already fetches the map from the
HubSpot API before the loop. The defect is that when `fetch_pipeline_stage_labels`
returns an empty dict (network error, missing config, or API shape change), the code
falls back to the raw internal stage ID (`closedlost`) instead of a human-readable
label (`Negotiating Remote`). Additionally, `_HS_STAGE_TO_LEAD_STATUS` is defined
locally inside `enrich_lead_from_deal` and only maps display labels, so a raw-ID
fallback silently leaves `lead_status` unchanged.

**Bug 2 — Property-to-owner connection not established**: `run_enrich_leads_from_hubspot`
already contains logic to resolve contacts whose `HubSpotMatch.internal_record_id` is
`NULL` via deal associations, but it only resolves matches whose status is `confirmed`
with a null `internal_record_id`. Contacts matched *before* the deal was confirmed end
up with status `pending` and `internal_record_id = NULL`, which the resolver loop skips.
The deal-association backfill path also silently continues when the v4 API returns an
empty `contacts` block, leaving the association chain broken.

**Bug 3 — Activities and history not importing**: `_resolve_associations` in
`hubspot_activity_converter_service.py` queries for `status='confirmed'` matches only.
Engagements whose deal or contact match is in `pending` state (or `confirmed` with
`internal_record_id = NULL`) produce an empty association list and are created with
`is_orphaned = True`. Once orphaned, no re-resolution pass runs later to link them to
the now-confirmed matches.

---

## Glossary

- **Bug_Condition (C)**: The set of conditions that trigger one of the three bugs —
  empty `stage_label_map`, unresolved contact match at association time, or orphaned
  engagement created before its match was confirmed.
- **Property (P)**: The desired correct behavior — lead shows a human-readable deal
  stage, the owner (e.g. Gilberto Olivares) appears on the property, and all
  engagements are linked to the correct lead timeline.
- **Preservation**: All existing non-destructive enrichment behavior, suppressed-status
  protection, idempotency checks, confirmed/rejected match preservation, and
  orphaned-interaction storage must continue to work exactly as before.
- **`enrich_lead_from_deal`**: Method in `backend/app/services/hubspot_matcher_service.py`
  that copies deal fields onto a Lead and syncs `hubspot_deal_stage` + `lead_status`.
- **`run_enrich_leads_from_hubspot`**: Pipeline task in
  `backend/app/tasks/hubspot_tasks.py` that iterates all confirmed deal/contact matches
  and calls `enrich_lead_from_deal` / `enrich_lead_from_contact`.
- **`run_convert_hubspot_activities`**: Pipeline task in `hubspot_tasks.py` that
  iterates all `HubSpotEngagement` records and calls
  `HubSpotActivityConverterService.convert_engagement`.
- **`_resolve_associations`**: Private method in
  `hubspot_activity_converter_service.py` that looks up confirmed `HubSpotMatch`
  records for each engagement's associated deal/contact IDs.
- **`stage_label_map`**: Dict of `{hubspot_internal_stage_id: display_label}` fetched
  from `/crm/v3/pipelines/deals` by `HubSpotClientService.fetch_pipeline_stage_labels`.
- **`HubSpotMatch`**: SQLAlchemy model (`hubspot_matches` table) with fields
  `hubspot_record_type`, `hubspot_id`, `internal_record_id`, `status`
  (`pending/confirmed/rejected`), and `confidence`.
- **`PropertyContact`**: SQLAlchemy model that links a `Contact` to a `Lead`
  (property), giving the owner visible on the property card.
- **`is_orphaned`**: Boolean flag on `Interaction` that is `True` when no confirmed
  `HubSpotMatch` was found at conversion time.

---

## Bug Details

### Bug 1 — Deal Stage Not Syncing

The bug manifests when `fetch_pipeline_stage_labels` returns an empty dict (API
failure, missing `HubSpotConfig`, or unexpected response shape), causing
`enrich_lead_from_deal` to fall back to the raw internal stage ID. The fallback raw ID
never matches a key in `_HS_STAGE_TO_LEAD_STATUS`, so `lead_status` is also left
unchanged.

**Formal Specification:**
```
FUNCTION isBugCondition_Stage(lead, deal, stage_label_map)
  INPUT:  lead           — Lead ORM instance
          deal           — HubSpotDeal ORM instance
          stage_label_map — dict (may be empty)
  OUTPUT: boolean

  stage_id := deal.raw_payload["properties"]["dealstage"]  -- e.g. "closedlost"
  RETURN stage_id IS NOT NULL
         AND stage_label_map.get(stage_id) IS NULL          -- map is empty or ID missing
         AND stage_id != stage_label_map.get(stage_id, stage_id)  -- fallback stores raw ID
END FUNCTION
```

**Concrete Examples:**
- `stage_id = "closedlost"`, `stage_label_map = {}` → stores `"closedlost"` instead of
  `"Negotiating Remote"`. `lead_status` is unchanged.
- `stage_id = "closedlost"`, `stage_label_map = {"closedlost": "Negotiating Remote"}` →
  stores `"Negotiating Remote"` and sets `lead_status = "negotiating_remote"`. ✓
- `stage_id = None`, `stage_label_map = {}` → no update at all (not a bug case).

### Bug 2 — Property-to-Owner Connection Not Established

The bug manifests in two overlapping scenarios for 2553 N Drake / Gilberto Olivares:

**Scenario A** — Contact was matched before the deal was confirmed. The contact's
`HubSpotMatch` ends up with `status='pending'` and `internal_record_id=NULL`.
`run_enrich_leads_from_hubspot`'s "resolve unlinked contacts" loop only queries
`status='confirmed'` with null `internal_record_id`, missing `status='pending'` rows.

**Scenario B** — The v4 association backfill for the deal returns an empty `contacts`
block (API timing issue or partial failure). The "match contacts via deal associations"
loop in `run_enrich_leads_from_hubspot` iterates over an empty list and never reaches
`enrich_lead_from_contact`, so no `PropertyContact` row is created.

**Formal Specification:**
```
FUNCTION isBugCondition_Owner(contact_match, deal_match, deal)
  INPUT:  contact_match — HubSpotMatch for a contact (may be pending or confirmed)
          deal_match    — HubSpotMatch for the deal (confirmed, non-null internal_record_id)
          deal          — HubSpotDeal ORM instance
  OUTPUT: boolean

  contact_ids_in_deal := deal.raw_payload
                           .get("associations", {})
                           .get("contacts", {})
                           .get("results", [])

  RETURN (
    -- Scenario A: contact match is pending with null internal_record_id
    (contact_match.status == 'pending'
     AND contact_match.internal_record_id IS NULL)
  ) OR (
    -- Scenario B: deal has no contacts in its association block
    contact_ids_in_deal IS EMPTY
    AND contact_match.hubspot_id links to deal_match via HubSpot associations API
  )
END FUNCTION
```

**Concrete Example:**
- Gilberto Olivares contact was imported, `match_contact()` ran (found no email/phone
  match), created a `HubSpotMatch` with `status='pending'`, `internal_record_id=NULL`.
- Deal for 2553 N Drake was imported later, `match_deal()` ran and confirmed the deal.
- Association backfill populated `deal.raw_payload["associations"]["contacts"]`.
- `run_enrich_leads_from_hubspot` resolves contacts from deal associations (**only**
  pending rows with `internal_record_id=NULL` — the query filter is wrong) OR the
  contacts block is still empty so the loop body never runs.
- Result: no `PropertyContact` row; Gilberto does not appear on the property.

### Bug 3 — Activities and History Not Importing

The bug manifests when `run_convert_hubspot_activities` runs while deal or contact
`HubSpotMatch` records are still in `pending` state (or `confirmed` with
`internal_record_id=NULL`). `_resolve_associations` only accepts `status='confirmed'`
matches with a non-null `internal_record_id`, returning an empty list for those
engagements. They are created as orphaned `Interaction` records and never re-associated
even after `run_enrich_leads_from_hubspot` later promotes those matches to confirmed.

**Formal Specification:**
```
FUNCTION isBugCondition_Activity(engagement, association_match)
  INPUT:  engagement        — HubSpotEngagement ORM instance
          association_match — HubSpotMatch for engagement's deal or contact
  OUTPUT: boolean

  confirmed_match_exists :=
    HubSpotMatch.query.filter_by(
      hubspot_id = association_match.hubspot_id,
      status     = 'confirmed'
    ).filter(internal_record_id IS NOT NULL).first()

  RETURN confirmed_match_exists IS NULL
         AND association_match.hubspot_id IN
               (engagement.raw_payload["associations"]["dealIds"]
                + engagement.raw_payload["associations"]["contactIds"])
END FUNCTION
```

**Concrete Examples:**
- Engagement (call with Gilberto Olivares) has `dealIds=[deal_hs_id]`. At conversion
  time, the deal match is `status='pending'` → `_resolve_associations` returns `[]`
  → `is_orphaned=True`. After `run_enrich_leads_from_hubspot` confirms the deal match,
  the engagement remains orphaned with no re-association pass.
- Engagement (note on 2553 N Drake deal) has `contactIds=[contact_hs_id]`. Contact
  match is `confirmed` but `internal_record_id=NULL` → same orphan result.
- EMAIL engagement type: not handled by `convert_engagement` (only NOTE/CALL/TASK are
  routed) → silently skipped; returns `None`.

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Existing non-null lead fields (other than `hubspot_deal_stage` and `lead_status`)
  must never be overwritten during HubSpot enrichment.
- When `lead_status` is `suppressed` or `do_not_contact`, HubSpot deal stage syncing
  must not overwrite that status.
- Engagements already converted (idempotency check via `hubspot_engagement_id`) must
  continue to be skipped without creating duplicates.
- `HubSpotMatch` records with status `confirmed` or `rejected` must not be re-matched
  during `run_hubspot_matching`.
- `PropertyContact` rows that already exist for a contact name + property must not be
  duplicated.
- The background thread pipeline (matching → enrichment → activity conversion →
  signal extraction → rescore) must continue to run regardless of Celery availability.
- Orphaned `Interaction` records (created when no match was found) must continue to
  store the raw payload so they can be re-associated later.

**Scope:**
All code paths that do NOT involve an empty `stage_label_map`, a `pending`-status
contact match, or an orphaned engagement must be completely unaffected by the fixes.

---

## Hypothesized Root Cause

### Bug 1

1. **Silent fallback in `enrich_lead_from_deal`**: When `stage_label_map` is empty or
   missing the deal's `dealstage` ID, the code does
   `stage_label = (stage_label_map or {}).get(stage_id, stage_id)`, which returns the
   raw ID unchanged. No warning is logged, so the caller never knows the translation
   failed.
2. **No on-demand fetch in `enrich_lead_from_deal`**: The function accepts
   `stage_label_map` as an optional parameter and defaults to `{}` when `None` is
   passed. It never attempts to fetch the map itself if the caller omits it (e.g.
   during `match_deal` when called without a pre-fetched map).
3. **`_HS_STAGE_TO_LEAD_STATUS` only maps display labels**: The dict is keyed on
   human-readable labels like `'Negotiating Remote'`, not raw IDs like `'closedlost'`.
   If the raw ID leaks through, `_HS_STAGE_TO_LEAD_STATUS.get(stage_label)` returns
   `None` and `lead_status` is left unchanged.

### Bug 2

1. **Wrong status filter in unresolved-contacts loop**: In `run_enrich_leads_from_hubspot`,
   the query for contacts needing resolution is:
   ```python
   HubSpotMatch.query.filter_by(hubspot_record_type='contact', status='confirmed')
               .filter(HubSpotMatch.internal_record_id.is_(None))
   ```
   Contacts matched before the deal was confirmed land in `status='pending'` with
   `internal_record_id=NULL`. They are never caught by this query.
2. **Empty association block not retried**: `_backfill_deal_contact_associations` logs
   `continue` when `contact_ids` is empty for a deal, without attempting a retry or
   emitting a warning. If the v4 API returns an empty result for any deal, the
   `raw_payload["associations"]["contacts"]["results"]` block stays empty and the
   deal-associations enrich loop in `run_enrich_leads_from_hubspot` never fires.

### Bug 3

1. **`_resolve_associations` only accepts confirmed + non-null matches**: The query
   `HubSpotMatch.query.filter_by(..., status='confirmed')` with an additional
   `.first()` check for non-null `internal_record_id` correctly rejects unresolved
   matches, but there is no follow-up pass to re-resolve orphaned interactions after
   the matches are later confirmed.
2. **No orphan re-resolution step in the pipeline**: `run_convert_hubspot_activities`
   has no "re-resolve previously orphaned interactions" phase. After
   `run_enrich_leads_from_hubspot` promotes pending contact matches to confirmed,
   no code revisits `is_orphaned=True` interactions to link them.
3. **EMAIL engagement type not handled**: `convert_engagement` routes `NOTE`, `CALL`,
   and `TASK` only. `EMAIL` type engagements fall through to the `else` branch, log a
   warning about "unrecognized type", and return `None`. Requirement 2.9 requires EMAIL
   to be imported as an `Interaction`.

---

## Correctness Properties

Property 1: Bug Condition — Deal Stage Always Shows Display Label

_For any_ HubSpot deal whose `dealstage` property maps to a known pipeline stage in the
portal, the fixed `enrich_lead_from_deal` SHALL store the human-readable display label
(e.g. `"Negotiating Remote"`) in `Lead.hubspot_deal_stage`, never the raw internal stage
ID (e.g. `"closedlost"`). When the display label exists in `_HS_STAGE_TO_LEAD_STATUS`
and `lead_status` is not `suppressed` or `do_not_contact`, `Lead.lead_status` SHALL also
be updated to the mapped value.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Bug Condition — Owner Contact Linked to Property

_For any_ lead that has a confirmed HubSpot deal match AND the deal has an associated
contact in HubSpot (regardless of whether the contact's `HubSpotMatch` is `pending` or
`confirmed` at enrichment time), the fixed `run_enrich_leads_from_hubspot` SHALL create
a `Contact` and `PropertyContact` row linking that contact to the lead, so the owner
name appears on the property.

**Validates: Requirements 2.4, 2.5, 2.6**

Property 3: Bug Condition — Orphaned Interactions Re-Resolved After Matching

_For any_ `Interaction` with `is_orphaned=True` whose associated HubSpot deal or contact
`HubSpotMatch` record now has `status='confirmed'` and a non-null `internal_record_id`,
the fixed `run_convert_hubspot_activities` SHALL create the missing
`InteractionAssociation` record linking the interaction to the correct lead, clearing
`is_orphaned` to `False`.

**Validates: Requirements 2.7, 2.8**

Property 4: Bug Condition — EMAIL Engagements Converted

_For any_ HubSpot engagement with `engagement_type='EMAIL'`, the fixed
`convert_engagement` SHALL create an `Interaction(interaction_type='email')` record,
applying the same association resolution and orphan logic as NOTE and CALL types.

**Validates: Requirement 2.9**

Property 5: Preservation — Non-Destructive Enrichment Unchanged

_For any_ lead field that is already non-null (other than `hubspot_deal_stage` and
`lead_status`), the fixed enrichment pipeline SHALL produce the same result as the
original pipeline, leaving the field unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

---

## Fix Implementation

### Bug 1 — `enrich_lead_from_deal` stage label fallback

**File**: `backend/app/services/hubspot_matcher_service.py`  
**Function**: `enrich_lead_from_deal`

**Specific Changes:**

1. **On-demand stage label fetch**: When `stage_label_map` is `None` or empty and a
   `stage_id` is present, fetch the pipeline stage labels from the HubSpot API before
   falling back to the raw ID:
   ```python
   if stage_id and not stage_label_map:
       try:
           from app.models.hubspot_config import HubSpotConfig
           from app.services.hubspot_client_service import HubSpotClientService
           _config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
           if _config:
               stage_label_map = HubSpotClientService(_config).fetch_pipeline_stage_labels("deals")
       except Exception as _exc:
           logger.warning("enrich_lead_from_deal: could not fetch stage labels: %s", _exc)
   ```
2. **Log a warning when falling back to raw ID**: After the `.get(stage_id, stage_id)`
   fallback, add:
   ```python
   if stage_label == stage_id:
       logger.warning(
           "enrich_lead_from_deal: stage_id=%r not in stage_label_map — "
           "storing raw ID. Pipeline labels: %s",
           stage_id, list(stage_label_map.keys()),
       )
   ```

### Bug 2 — Contact match resolution in `run_enrich_leads_from_hubspot`

**File**: `backend/app/tasks/hubspot_tasks.py`  
**Function**: `run_enrich_leads_from_hubspot`

**Specific Changes:**

1. **Widen the unresolved-contacts query to include `pending` status**: Change:
   ```python
   # BEFORE
   HubSpotMatch.query
       .filter_by(hubspot_record_type='contact', status='confirmed')
       .filter(HubSpotMatch.internal_record_id.is_(None))
   ```
   To:
   ```python
   # AFTER
   HubSpotMatch.query
       .filter_by(hubspot_record_type='contact')
       .filter(HubSpotMatch.status.in_(['confirmed', 'pending']))
       .filter(HubSpotMatch.internal_record_id.is_(None))
   ```
2. **Warn + retry on empty contacts block**: In the deal-associations enrich loop, when
   `contact_ids_in_deal` is empty after reading `raw_payload`, attempt one v4 retry for
   that single deal before logging a warning and continuing:
   ```python
   if not contact_ids:
       logger.warning(
           "run_enrich_leads_from_hubspot: deal %s has empty contacts block — "
           "retrying v4 associations fetch", deal.hubspot_id,
       )
       try:
           assoc_map = client.fetch_deal_contact_associations([deal.hubspot_id],
                                                              allow_partial=False)
           contact_ids_raw = assoc_map.get(deal.hubspot_id, [])
           contact_ids = [{"id": cid} for cid in contact_ids_raw]
       except Exception as retry_exc:
           logger.warning("retry failed for deal %s: %s", deal.hubspot_id, retry_exc)
   ```
   The `HubSpotClientService` instance is already available in the enrichment loop scope
   (it's constructed to fetch `stage_label_map`). The retry only fires once, so the
   fallback is bounded.

### Bug 3 — Orphan re-resolution and EMAIL support

**File**: `backend/app/tasks/hubspot_tasks.py`  
**Function**: `run_convert_hubspot_activities`

**Specific Changes:**

1. **Add a re-resolution pass for orphaned interactions**: After the main conversion
   loop, add a second pass that queries `Interaction.is_orphaned=True` records and
   re-runs `_resolve_associations` (or an equivalent query) against the now-updated
   `HubSpotMatch` table:
   ```python
   # Re-resolve previously orphaned interactions
   orphaned = Interaction.query.filter_by(is_orphaned=True, source='hubspot_import').all()
   re_linked = 0
   for interaction in orphaned:
       associations = converter._resolve_associations_by_engagement_id(
           interaction.hubspot_engagement_id
       )
       if associations:
           for assoc in associations:
               existing = InteractionAssociation.query.filter_by(
                   interaction_id=interaction.id,
                   target_type=assoc['target_type'],
                   target_id=assoc['target_id'],
               ).first()
               if existing is None:
                   db.session.add(InteractionAssociation(...))
           interaction.is_orphaned = False
           db.session.commit()
           re_linked += 1
   ```
   The helper `_resolve_associations_by_engagement_id` looks up the original
   `HubSpotEngagement` by its `hubspot_id` and delegates to the existing
   `_resolve_associations` method.

**File**: `backend/app/services/hubspot_activity_converter_service.py`  
**Function**: `convert_engagement`

2. **Handle EMAIL engagement type**: Add an `elif etype == 'EMAIL': return
   self.convert_email(engagement)` branch, and implement `convert_email` mirroring
   `convert_note` with `interaction_type='email'`.

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate each bug on the unfixed code, then verify the fixes work and preservation
holds across all non-buggy paths.

All tests live in `backend/tests/`. Property-based tests use `hypothesis`. Run with:
```bash
cd backend && pytest tests/test_hubspot_sync_bugs.py -v
```

---

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the
fixes, confirming or refuting the root cause analysis.

**Test Plan**: Write tests against the *current* (unfixed) code using SQLite in-memory
fixtures (matching the project's existing `conftest.py` pattern). Each test asserts the
correct post-fix behavior — running on unfixed code should fail, confirming the bug.

**Test Cases:**

1. **Bug 1 — Empty stage_label_map stores raw ID** (will fail on unfixed code):
   Create a `HubSpotDeal` with `dealstage="closedlost"`. Call `enrich_lead_from_deal`
   with `stage_label_map={}`. Assert `lead.hubspot_deal_stage == "Negotiating Remote"`.
   *Expected failure*: stores `"closedlost"` instead.

2. **Bug 1 — lead_status not updated from raw ID** (will fail on unfixed code):
   Same setup. Assert `lead.lead_status == "negotiating_remote"`.
   *Expected failure*: `lead_status` is unchanged.

3. **Bug 2 — Pending contact match not resolved** (will fail on unfixed code):
   Create a confirmed deal match and a `pending` contact match with
   `internal_record_id=NULL` for the same deal. Run `run_enrich_leads_from_hubspot`.
   Assert the contact's match now has `internal_record_id == lead.id` and a
   `PropertyContact` row exists.
   *Expected failure*: the pending match is never resolved.

4. **Bug 3 — Orphaned interaction not re-linked** (will fail on unfixed code):
   Create an `Interaction(is_orphaned=True)` whose engagement has `dealIds=[deal_hs_id]`.
   Confirm the deal match. Run `run_convert_hubspot_activities`. Assert
   `interaction.is_orphaned == False` and an `InteractionAssociation` row exists.
   *Expected failure*: interaction remains orphaned.

5. **Bug 3 — EMAIL engagement silently skipped** (will fail on unfixed code):
   Create a `HubSpotEngagement(engagement_type='EMAIL')`. Run `run_convert_hubspot_activities`.
   Assert an `Interaction(interaction_type='email')` was created.
   *Expected failure*: returns `None`, no interaction created.

**Expected Counterexamples:**
- `lead.hubspot_deal_stage` equals the raw HubSpot stage ID string.
- `lead.lead_status` is unchanged after enrichment.
- `PropertyContact` row is absent for confirmed deal + pending contact.
- `is_orphaned` remains `True` after the pipeline runs.

---

### Fix Checking

**Goal**: Verify that for all inputs where the bug conditions hold, the fixed functions
produce the expected behavior.

**Pseudocode:**
```
FOR ALL (lead, deal) WHERE isBugCondition_Stage(lead, deal, stage_label_map={}) DO
  enrich_lead_from_deal_FIXED(lead, deal, stage_label_map={})
  ASSERT lead.hubspot_deal_stage == stage_label_map_fetched.get(stage_id)
  ASSERT lead.lead_status == _HS_STAGE_TO_LEAD_STATUS.get(lead.hubspot_deal_stage)
END FOR

FOR ALL (contact_match, deal_match) WHERE isBugCondition_Owner(...) DO
  run_enrich_leads_from_hubspot_FIXED()
  ASSERT contact_match.internal_record_id == deal_match.internal_record_id
  ASSERT PropertyContact.query.filter_by(property_id=lead.id).count() >= 1
END FOR

FOR ALL interaction WHERE isBugCondition_Activity(interaction, ...) DO
  run_convert_hubspot_activities_FIXED()
  ASSERT interaction.is_orphaned == False
  ASSERT InteractionAssociation.query.filter_by(interaction_id=interaction.id).count() >= 1
END FOR
```

---

### Preservation Checking

**Goal**: Verify that for all inputs where the bug conditions do NOT hold, the fixed
functions produce exactly the same result as the original functions.

**Pseudocode:**
```
FOR ALL (lead, deal) WHERE NOT isBugCondition_Stage(lead, deal, stage_label_map) DO
  ASSERT enrich_lead_from_deal_ORIGINAL(lead, deal) ==
         enrich_lead_from_deal_FIXED(lead, deal)
END FOR

FOR ALL interaction WHERE NOT isBugCondition_Activity(interaction, ...) DO
  ASSERT convert_engagement_ORIGINAL(engagement) ==
         convert_engagement_FIXED(engagement)
END FOR
```

**Testing Approach**: Property-based testing with Hypothesis is recommended for
preservation checking because the input space (arbitrary deal `raw_payload` shapes,
various lead field combinations, mixed engagement types) is large and manual unit tests
would miss edge cases.

**Preservation Test Cases:**

1. **Non-null lead fields not overwritten**: Generate leads with random non-null values
   in all enrichable fields; assert none change after enrichment.
2. **Suppressed status protected**: Lead with `lead_status='suppressed'`; assert status
   unchanged after any deal stage sync.
3. **Duplicate PropertyContact prevention**: Run enrichment twice for the same
   contact; assert only one `PropertyContact` row exists.
4. **Idempotency of activity conversion**: Run `run_convert_hubspot_activities` twice;
   assert converted count on second run is 0.
5. **Confirmed/rejected match not re-matched**: `HubSpotMatch` with
   `status='confirmed'` or `'rejected'`; assert `run_hubspot_matching` does not
   overwrite it.

---

### Unit Tests

- `test_enrich_lead_from_deal_with_empty_stage_label_map_fetches_from_api`
- `test_enrich_lead_from_deal_with_known_stage_id_stores_display_label`
- `test_enrich_lead_from_deal_warns_when_stage_id_not_in_map`
- `test_run_enrich_resolves_pending_contact_match_via_deal_association`
- `test_run_enrich_retries_empty_contacts_block_via_v4_api`
- `test_run_convert_re_resolves_orphaned_interactions_after_match_confirmed`
- `test_convert_engagement_email_creates_interaction_type_email`
- `test_convert_note_idempotent_on_second_run`

### Property-Based Tests

- Generate random `stage_label_map` dicts (possibly empty) and assert
  `lead.hubspot_deal_stage` is always a value from the map when the key exists.
- Generate arbitrary lead field combinations and assert non-null fields are never
  overwritten by `enrich_lead_from_deal` or `enrich_lead_from_contact`.
- Generate random sequences of engagement types (NOTE/CALL/TASK/EMAIL/unknown) and
  assert only recognized types produce non-None results from `convert_engagement`.
- Generate many contact+deal association scenarios (pending, confirmed, null
  `internal_record_id`) and assert `PropertyContact` rows are created exactly once.

### Integration Tests

- Full pipeline run (matching → enrichment → activity conversion) with a seeded
  HubSpot deal + contact + engagement fixture; assert all three bugs are resolved
  end-to-end.
- Verify that 2553 N Drake shows Gilberto Olivares as owner after a full pipeline run
  with the existing fixture data.
- Verify that activities for 2553 N Drake appear in the timeline after pipeline
  completes.
- Verify that `hubspot_deal_stage` on 2553 N Drake shows `"Negotiating Remote"` (not
  `"closedlost"`) after enrichment.
