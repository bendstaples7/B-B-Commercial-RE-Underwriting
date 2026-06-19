# Bugfix Requirements Document

## Introduction

Three related bugs in the HubSpot sync pipeline are preventing CRM data from
surfacing correctly in the platform. Bug 1 covers deal stages not reflecting
the current HubSpot pipeline stage on a lead. Bug 2 covers property-to-owner
connections not being established even when the connection exists in both
HubSpot and the import sheet (specific example: 2553 N Drake / Gilberto
Olivares). Bug 3 covers HubSpot activities (calls, emails, notes, tasks) and
deal/contact history not being imported or synced into the platform.

---

## Bug Analysis

### Current Behavior (Defect)

**Bug 1 — Deal stage not syncing**

1.1 WHEN a deal's stage is updated in HubSpot AND the platform runs a full
    import THEN the system does not update the lead's `hubspot_deal_stage`
    field to reflect the new stage value.

1.2 WHEN `enrich_lead_from_deal` maps a HubSpot internal stage ID (e.g.
    `closedlost`) to a display label AND the `stage_label_map` is empty or
    missing for that ID THEN the system stores the raw internal stage ID
    instead of the human-readable label (e.g. stores `closedlost` instead of
    `Negotiating Remote`).

1.3 WHEN a lead's `lead_status` should be updated to match the newly synced
    deal stage AND the stage label does not exactly match a key in
    `_HS_STAGE_TO_LEAD_STATUS` THEN the system leaves `lead_status`
    unchanged, so the platform stage and the HubSpot stage are out of sync.

**Bug 2 — Property-to-owner connection not established**

2.1 WHEN a HubSpot contact is associated to a deal via the v4 associations API
    AND that contact's `match_contact()` run produces a `HubSpotMatch` record
    with `internal_record_id = NULL` (because the deal was not yet confirmed
    at match time) THEN the system does not link the contact to the property,
    so the owner does not appear on the lead.

2.2 WHEN `run_enrich_leads_from_hubspot` resolves an unlinked contact via
    deal associations AND the deal's `raw_payload["associations"]["contacts"]`
    block is still empty after the import (association backfill incomplete)
    THEN the system cannot resolve the contact-to-property link, leaving the
    owner disconnected.

2.3 WHEN a lead is imported from a Google Sheet AND a HubSpot contact for the
    same owner (e.g. Gilberto Olivares at 2553 N Drake) exists with a
    confirmed deal match THEN the system does not create a `PropertyContact`
    row linking that contact to the lead, so the owner name and contact
    details do not appear on the property.

**Bug 3 — Activities and history not importing**

3.1 WHEN HubSpot engagements (calls, emails, notes, tasks) exist for a deal or
    contact THEN the system does not import them as `Interaction` or `Task`
    records when the contact match has `internal_record_id = NULL`, leaving
    all activities marked as orphaned.

3.2 WHEN `run_convert_hubspot_activities` runs AND a HubSpot engagement's
    associated deal or contact does not have a confirmed `HubSpotMatch` with a
    non-null `internal_record_id` THEN the system creates an `Interaction`
    with `is_orphaned = True` and does not associate it with any lead, making
    it invisible in the activity timeline.

3.3 WHEN the engagements import task runs AND Celery is not available THEN the
    system does not fall back to the background pipeline thread for the
    activity conversion step, so activities are never converted even after the
    background thread completes matching and enrichment.

---

### Expected Behavior (Correct)

**Bug 1 — Deal stage**

2.1 WHEN a deal's stage is updated in HubSpot AND a full import or webhook
    sync runs THEN the system SHALL update `Lead.hubspot_deal_stage` to the
    current stage's display label (e.g. `Negotiating Remote`).

2.2 WHEN `enrich_lead_from_deal` is called AND `stage_label_map` does not
    contain the deal's `dealstage` ID THEN the system SHALL fetch the
    pipeline stage labels from the HubSpot API before falling back to the raw
    ID, so the lead always shows a human-readable label.

2.3 WHEN the stage display label matches a key in `_HS_STAGE_TO_LEAD_STATUS`
    THEN the system SHALL update `Lead.lead_status` to the mapped value,
    unless the current status is `suppressed` or `do_not_contact`.

**Bug 2 — Property-to-owner connection**

2.4 WHEN a HubSpot contact is associated to a confirmed deal AND the contact's
    `HubSpotMatch.internal_record_id` is NULL THEN the system SHALL resolve
    the contact-to-property link via the deal association and update the match
    record, creating a `PropertyContact` row so the owner appears on the lead.

2.5 WHEN association backfill produces an empty contacts block for a deal
    THEN the system SHALL log a warning and SHALL retry the v4 associations
    fetch for that deal before marking the import run complete, so
    unresolvable contacts are surfaced rather than silently dropped.

2.6 WHEN a lead imported from any source (Google Sheets, DfD, GIS) has a
    confirmed HubSpot deal match AND that deal has associated contact IDs
    THEN the system SHALL create `Contact` and `PropertyContact` rows for
    those contacts so the owner is visible in the platform.

**Bug 3 — Activities and history**

2.7 WHEN `run_convert_hubspot_activities` runs after matching and enrichment
    THEN the system SHALL re-resolve associations for engagements whose
    linked contacts or deals now have confirmed matches with non-null
    `internal_record_id`, converting them from orphaned to properly linked
    `Interaction` records.

2.8 WHEN a HubSpot NOTE, CALL, or TASK engagement is associated to a deal
    that has a confirmed `HubSpotMatch` THEN the system SHALL create the
    corresponding `Interaction` or `Task` record linked to the matching lead,
    even if the engagement's contact association is unresolved.

2.9 WHEN the background pipeline thread completes matching and enrichment
    THEN the system SHALL run activity conversion as the next step, and SHALL
    import all NOTE, CALL, TASK, and EMAIL engagement types as `Interaction`
    or `Task` records associated with the correct lead.

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a lead already has a non-null value in any field other than
    `hubspot_deal_stage` and `lead_status` THEN the system SHALL CONTINUE TO
    leave that field unchanged during HubSpot enrichment (non-destructive
    enrichment is preserved).

3.2 WHEN a lead's `lead_status` is `suppressed` or `do_not_contact` THEN the
    system SHALL CONTINUE TO prevent HubSpot deal stage syncing from
    overwriting that status.

3.3 WHEN a HubSpot engagement has already been converted to an `Interaction`
    or `Task` (idempotency check via `hubspot_engagement_id`) THEN the system
    SHALL CONTINUE TO skip re-conversion, returning `None` without creating
    duplicate records.

3.4 WHEN a `HubSpotMatch` record has status `confirmed` or `rejected` THEN
    the system SHALL CONTINUE TO skip re-matching for that record during
    `run_hubspot_matching`, preserving reviewer decisions.

3.5 WHEN the contact-to-property link (`PropertyContact`) already exists for a
    given contact name and property THEN the system SHALL CONTINUE TO skip
    creating a duplicate `PropertyContact` row.

3.6 WHEN an import is triggered and Celery is unavailable THEN the system
    SHALL CONTINUE TO run the post-import pipeline via the background thread
    (matching → enrichment → activity conversion → signal extraction →
    rescore).

3.7 WHEN an `Interaction` is created with `is_orphaned = True` because no
    confirmed match was found at conversion time THEN the system SHALL
    CONTINUE TO store the raw payload so it can be re-associated later.
