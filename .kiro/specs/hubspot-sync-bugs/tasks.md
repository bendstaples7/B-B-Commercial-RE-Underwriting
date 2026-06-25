# Implementation Plan

- [x] 1. Write bug condition exploration tests (BEFORE implementing any fix)
  - **Property 1: Bug Condition** - Three HubSpot Sync Bugs (Stage Label Fallback / Pending Contact / Orphaned Activity)
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fixes when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate each bug on the current code
  - **Scoped PBT Approach**: For each deterministic bug condition, scope the property to the concrete failing case to ensure reproducibility
  - Create `backend/tests/test_hubspot_sync_bugs.py` with the following exploration tests:

  **Bug 1 — Stage label fallback (from Bug Condition in design: `stage_label_map = {}` + `stage_id = "closedlost"`)**
  - Test `test_bug1_empty_stage_label_map_stores_raw_id`: call `enrich_lead_from_deal` with `stage_label_map={}` and a deal whose `dealstage="closedlost"`. Assert `lead.hubspot_deal_stage == "Negotiating Remote"`. On unfixed code: stores `"closedlost"` instead.
  - Test `test_bug1_lead_status_not_updated_from_raw_id`: same setup. Assert `lead.lead_status == "negotiating_remote"`. On unfixed code: `lead_status` is unchanged.
  - Property-based variant: for all non-empty `stage_label_map` dicts that contain `stage_id`, assert `lead.hubspot_deal_stage` is always the mapped display label — never the raw ID.

  **Bug 2 — Pending contact match not resolved (from Bug Condition in design: `contact_match.status='pending'`, `internal_record_id=NULL`)**
  - Test `test_bug2_pending_contact_match_not_resolved`: create a confirmed deal match for a lead + a `HubSpotMatch(status='pending', internal_record_id=NULL)` for a contact associated to that deal. Call `run_enrich_leads_from_hubspot`. Assert `contact_match.internal_record_id == lead.id` and a `PropertyContact` row exists. On unfixed code: query filter `status='confirmed'` misses the pending row, contact remains unresolved.

  **Bug 3a — Orphaned interaction not re-linked (from Bug Condition in design: `is_orphaned=True` + deal match later confirmed)**
  - Test `test_bug3a_orphaned_interaction_not_relinked`: create a `HubSpotEngagement` with `dealIds=[deal_hs_id]`. Run `run_convert_hubspot_activities` while deal match is still `pending` → verify `Interaction.is_orphaned=True`. Then confirm the deal match. Re-run `run_convert_hubspot_activities`. Assert `interaction.is_orphaned == False` and `InteractionAssociation` row exists. On unfixed code: orphan remains after the second run.

  **Bug 3b — EMAIL engagement silently skipped (from Bug Condition in design: `engagement_type='EMAIL'` falls through to else branch)**
  - Test `test_bug3b_email_engagement_silently_skipped`: create a `HubSpotEngagement(engagement_type='EMAIL')` with a confirmed deal association. Call `converter.convert_engagement(engagement)`. Assert result is not `None` and `Interaction(interaction_type='email')` was created. On unfixed code: returns `None`, no interaction created.

  - Run all exploration tests on **UNFIXED code**: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v`
  - **EXPECTED OUTCOME**: All exploration tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found (e.g. `lead.hubspot_deal_stage = "closedlost"`, `PropertyContact` absent, `is_orphaned = True` after pipeline re-run, `convert_engagement` returns `None` for EMAIL)
  - Mark task complete when tests are written, run on unfixed code, and all failures are documented
  - _Requirements: 1.2, 2.1, 2.2, 3.1, 3.2_

- [x] 2. Write preservation property tests (BEFORE implementing any fix)
  - **Property 2: Preservation** - Non-Destructive Enrichment, Suppressed Status, Idempotency, Duplicate Prevention
  - **IMPORTANT**: Follow observation-first methodology — run unfixed code with non-buggy inputs first, observe outputs, then write tests
  - **Observe on UNFIXED code** (none of these inputs hit the bug conditions):
    - Observe: lead with non-null `phone_1` → enrichment does not overwrite it
    - Observe: lead with `lead_status='suppressed'` + any deal stage → `lead_status` stays `'suppressed'`
    - Observe: same engagement converted twice → second call returns `None`, no duplicate `Interaction`
    - Observe: same contact+property enriched twice → only one `PropertyContact` row exists
    - Observe: `HubSpotMatch(status='confirmed')` → `run_hubspot_matching` does not re-match it
  - Write property-based tests (Hypothesis) in `backend/tests/test_hubspot_sync_bugs.py`:

  **Preservation Test 1 — Non-null lead fields not overwritten**
  - `@given(st.text(min_size=1))` for field values. Generate lead with non-null `phone_1`, `email_1`, `mailing_address`, `county_assessor_pin`. Call `enrich_lead_from_deal` and `enrich_lead_from_contact`. Assert all pre-existing non-null fields are unchanged. (`hubspot_deal_stage` and `lead_status` are exempt from this rule.)
  - From Preservation Requirements in design: "Existing non-null lead fields (other than `hubspot_deal_stage` and `lead_status`) must never be overwritten during HubSpot enrichment."

  **Preservation Test 2 — Suppressed status protected**
  - `@given(st.sampled_from(['suppressed', 'do_not_contact']))`. For lead with that status, call `enrich_lead_from_deal` with any `stage_label_map`. Assert `lead.lead_status` is unchanged.
  - From Preservation Requirements in design: "When `lead_status` is `suppressed` or `do_not_contact`, HubSpot deal stage syncing must not overwrite that status."

  **Preservation Test 3 — Idempotency of activity conversion**
  - Convert a NOTE and a CALL engagement once; record IDs created. Convert the same engagements again. Assert second run returns `None` for both and the total `Interaction` count is unchanged.
  - From Preservation Requirements in design: "Engagements already converted (idempotency check via `hubspot_engagement_id`) must continue to be skipped."

  **Preservation Test 4 — No duplicate PropertyContact on double enrichment**
  - Enrich the same lead from the same HubSpot contact twice. Assert `PropertyContact.query.filter_by(property_id=lead.id).count() == 1`.
  - From Preservation Requirements in design: "`PropertyContact` rows that already exist for a contact name + property must not be duplicated."

  **Preservation Test 5 — Confirmed/rejected match not re-matched**
  - `@given(st.sampled_from(['confirmed', 'rejected']))`. Create `HubSpotMatch(status=status)`. Run `run_hubspot_matching`. Assert match status is unchanged.
  - From Preservation Requirements in design: "`HubSpotMatch` records with status `confirmed` or `rejected` must not be re-matched."

  - Run all preservation tests on **UNFIXED code**: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k preservation -v`
  - **EXPECTED OUTCOME**: All preservation tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix Bug 1 — `enrich_lead_from_deal` stage label silent fallback

  - [x] 3.1 Add on-demand stage label fetch when `stage_label_map` is empty
    - File: `backend/app/services/hubspot_matcher_service.py`, function `enrich_lead_from_deal`
    - After the `stage_id = props.get("dealstage") or None` line, add a guard that fires when `stage_id` is present AND `stage_label_map` is empty:
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
    - _Bug_Condition: `isBugCondition_Stage` — `stage_id IS NOT NULL AND stage_label_map.get(stage_id) IS NULL`_
    - _Expected_Behavior: `lead.hubspot_deal_stage` stores the display label, not the raw stage ID_
    - _Preservation: stage label fetch is attempted only when `stage_label_map` is empty; all other paths unchanged_
    - _Requirements: 2.2_

  - [x] 3.2 Add warning log when falling back to raw stage ID
    - Immediately after the `stage_label = (stage_label_map or {}).get(stage_id, stage_id)` line, add:
      ```python
      if stage_label == stage_id:
          logger.warning(
              "enrich_lead_from_deal: stage_id=%r not in stage_label_map — "
              "storing raw ID. Pipeline labels: %s",
              stage_id, list((stage_label_map or {}).keys()),
          )
      ```
    - This surfaces the failure clearly in logs rather than silently storing the raw ID
    - _Requirements: 2.2_

  - [x] 3.3 Verify Bug 1 exploration test now passes
    - **Property 1: Expected Behavior** - Stage Label Display (Bug 1)
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug1" -v`
    - **EXPECTED OUTCOME**: `test_bug1_empty_stage_label_map_stores_raw_id` and `test_bug1_lead_status_not_updated_from_raw_id` PASS
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. Fix Bug 2 — `run_enrich_leads_from_hubspot` pending contact resolution and empty association retry

  - [x] 4.1 Widen unresolved-contacts query to include `pending` status
    - File: `backend/app/tasks/hubspot_tasks.py`, function `run_enrich_leads_from_hubspot`
    - Find the `unresolved_contact_matches` query in the "resolve contacts whose match has `internal_record_id=NULL`" section
    - Change `.filter_by(hubspot_record_type='contact', status='confirmed')` to:
      ```python
      HubSpotMatch.query
          .filter_by(hubspot_record_type='contact')
          .filter(HubSpotMatch.status.in_(['confirmed', 'pending']))
          .filter(HubSpotMatch.internal_record_id.is_(None))
          .all()
      ```
    - This catches contacts that were matched before the deal was confirmed (Bug 2 Scenario A)
    - _Bug_Condition: `isBugCondition_Owner` Scenario A — `contact_match.status == 'pending' AND contact_match.internal_record_id IS NULL`_
    - _Expected_Behavior: `PropertyContact` row created linking contact to lead; `contact_match.internal_record_id` updated_
    - _Preservation: only changes the status filter; confirmed+non-null matches are unaffected; rejected matches still excluded_
    - _Requirements: 2.4, 2.6_

  - [x] 4.2 Add single retry on empty contacts block from v4 API
    - File: `backend/app/tasks/hubspot_tasks.py`, function `run_enrich_leads_from_hubspot`
    - In the "Also match contacts via deal associations" loop, before iterating `contact_ids`, add:
      ```python
      if not contact_ids:
          logger.warning(
              "run_enrich_leads_from_hubspot: deal %s has empty contacts block — "
              "retrying v4 associations fetch", deal.hubspot_id,
          )
          try:
              assoc_map = _client.fetch_deal_contact_associations(
                  [deal.hubspot_id]
              )
              raw_ids = assoc_map.get(deal.hubspot_id, [])
              contact_ids = [{"id": cid} for cid in raw_ids]
          except Exception as _retry_exc:
              logger.warning(
                  "run_enrich_leads_from_hubspot: retry failed for deal %s: %s",
                  deal.hubspot_id, _retry_exc,
              )
      ```
    - Note: `_client` must be available in this scope — ensure `HubSpotClientService` instance is constructed (it already is for `stage_label_map` fetch; reuse that reference, renaming it `_client` where needed)
    - This addresses Bug 2 Scenario B — empty `contacts` block from v4 API
    - _Bug_Condition: `isBugCondition_Owner` Scenario B — `contact_ids_in_deal IS EMPTY`_
    - _Expected_Behavior: retry fetches the contacts block once; if successful, enrichment proceeds_
    - _Preservation: retry only fires when block is empty; existing non-empty paths are unchanged; only one retry attempt_
    - _Requirements: 2.5, 2.6_

  - [x] 4.3 Verify Bug 2 exploration test now passes
    - **Property 1: Expected Behavior** - Owner Contact Linked to Property (Bug 2)
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug2" -v`
    - **EXPECTED OUTCOME**: `test_bug2_pending_contact_match_not_resolved` PASSES; `PropertyContact` row exists for the contact
    - _Requirements: 2.4, 2.5, 2.6_

- [x] 5. Fix Bug 3 — Orphan re-resolution pass and EMAIL engagement type support

  - [x] 5.1 Add `convert_email` method to `HubSpotActivityConverterService`
    - File: `backend/app/services/hubspot_activity_converter_service.py`
    - Add a new public method `convert_email(self, engagement)` mirroring `convert_note` exactly, but with `interaction_type='email'`:
      ```python
      def convert_email(self, engagement):
          """
          Convert a HubSpot EMAIL engagement to an internal Interaction(type='email').

          Idempotent: returns None if hubspot_engagement_id already exists.
          Body is sourced from metadata.body, falling back to engagement.bodyPreview.
          occurred_at is sourced from engagement.createdAt (milliseconds).
          """
          if self._interaction_exists(engagement.hubspot_id):
              logger.debug(
                  "Interaction for hubspot_engagement_id=%s already exists — skipping.",
                  engagement.hubspot_id,
              )
              return None

          body = self._extract_note_body(engagement.raw_payload)  # same extraction as NOTE
          occurred_at = self._parse_ms_timestamp(
              engagement.raw_payload.get('engagement', {}).get('createdAt')
          )

          associations = self._resolve_associations(engagement)
          is_orphaned = len(associations) == 0

          interaction = Interaction(
              interaction_type='email',
              body=body,
              occurred_at=occurred_at,
              source='hubspot_import',
              hubspot_engagement_id=engagement.hubspot_id,
              raw_payload=engagement.raw_payload,
              is_orphaned=is_orphaned,
          )
          db.session.add(interaction)
          db.session.flush()

          for assoc in associations:
              db.session.add(InteractionAssociation(
                  interaction_id=interaction.id,
                  target_type=assoc['target_type'],
                  target_id=assoc['target_id'],
              ))

          db.session.commit()
          logger.info(
              "Created Interaction(id=%s, type=email) from HubSpot engagement %s (orphaned=%s).",
              interaction.id,
              engagement.hubspot_id,
              is_orphaned,
          )
          self._extract_signals_for_interaction(interaction, associations)
          return interaction
      ```
    - _Bug_Condition: `isBugCondition_Activity` EMAIL variant — `engagement_type='EMAIL'` falls through to unrecognized branch_
    - _Expected_Behavior: `Interaction(interaction_type='email')` is created; association and orphan logic identical to NOTE/CALL_
    - _Preservation: NOTE/CALL/TASK conversion paths are unchanged; EMAIL is additive_
    - _Requirements: 2.9_

  - [x] 5.2 Route EMAIL in `convert_engagement`
    - File: `backend/app/services/hubspot_activity_converter_service.py`, method `convert_engagement`
    - Add `elif etype == 'EMAIL': return self.convert_email(engagement)` immediately before the `else` branch:
      ```python
      elif etype == 'EMAIL':
          return self.convert_email(engagement)
      ```
    - _Requirements: 2.9_

  - [x] 5.3 Add `_resolve_associations_by_engagement_id` helper to `HubSpotActivityConverterService`
    - File: `backend/app/services/hubspot_activity_converter_service.py`
    - Add a private method that looks up the original `HubSpotEngagement` by its `hubspot_id` string and delegates to the existing `_resolve_associations`:
      ```python
      def _resolve_associations_by_engagement_id(self, hubspot_engagement_id):
          """Look up the HubSpotEngagement by ID and resolve its associations.

          Used by the orphan re-resolution pass in run_convert_hubspot_activities.
          Returns [] if the engagement no longer exists in the database.
          """
          from app.models.hubspot_engagement import HubSpotEngagement
          engagement = HubSpotEngagement.query.filter_by(
              hubspot_id=str(hubspot_engagement_id)
          ).first()
          if engagement is None:
              return []
          return self._resolve_associations(engagement)
      ```
    - _Requirements: 2.7_

  - [x] 5.4 Add orphan re-resolution pass to `run_convert_hubspot_activities`
    - File: `backend/app/tasks/hubspot_tasks.py`, function `run_convert_hubspot_activities`
    - After the main conversion loop (after the `logger.info("run_convert_hubspot_activities: complete...")` line), add a second pass:
      ```python
      # --- Re-resolve previously orphaned interactions -------------------
      # After run_enrich_leads_from_hubspot confirms pending matches, revisit
      # all orphaned HubSpot-imported Interactions and link them if a confirmed
      # match now exists for their associated deal/contact.
      from app.models import Interaction, InteractionAssociation

      orphaned = (
          Interaction.query
          .filter_by(is_orphaned=True, source='hubspot_import')
          .all()
      )
      re_linked = 0
      re_link_errors = 0
      for interaction in orphaned:
          try:
              new_assocs = converter._resolve_associations_by_engagement_id(
                  interaction.hubspot_engagement_id
              )
              if not new_assocs:
                  continue
              for assoc in new_assocs:
                  existing = InteractionAssociation.query.filter_by(
                      interaction_id=interaction.id,
                      target_type=assoc['target_type'],
                      target_id=assoc['target_id'],
                  ).first()
                  if existing is None:
                      db.session.add(InteractionAssociation(
                          interaction_id=interaction.id,
                          target_type=assoc['target_type'],
                          target_id=assoc['target_id'],
                      ))
              interaction.is_orphaned = False
              db.session.commit()
              re_linked += 1
              logger.debug(
                  "run_convert_hubspot_activities: re-linked orphaned interaction id=%s",
                  interaction.id,
              )
          except Exception as exc:
              logger.warning(
                  "run_convert_hubspot_activities: re-link error for interaction id=%s: %s",
                  interaction.id, exc,
              )
              re_link_errors += 1
              db.session.rollback()

      logger.info(
          "run_convert_hubspot_activities: orphan re-resolution — re_linked=%d errors=%d",
          re_linked, re_link_errors,
      )
      ```
    - _Bug_Condition: `isBugCondition_Activity` — `is_orphaned=True` on Interaction whose match is now confirmed_
    - _Expected_Behavior: `InteractionAssociation` created, `is_orphaned` set to `False`_
    - _Preservation: pass only fires for `is_orphaned=True` records; already-linked interactions are untouched; second-run is idempotent (existing association skipped)_
    - _Requirements: 2.7, 2.8_

  - [x] 5.5 Verify Bug 3 exploration tests now pass
    - **Property 1: Expected Behavior** - Orphan Re-Resolution and EMAIL Support (Bug 3)
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug3" -v`
    - **EXPECTED OUTCOME**: `test_bug3a_orphaned_interaction_not_relinked` and `test_bug3b_email_engagement_silently_skipped` PASS
    - _Requirements: 2.7, 2.8, 2.9_

- [x] 6. Checkpoint — Verify all tests pass and preservation holds

  - [x] 6.1 Run full test file — all exploration tests must pass
    - **Property 1: Expected Behavior** - All Three Bugs Fixed
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v`
    - **EXPECTED OUTCOME**: All exploration tests PASS (confirms all three bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 6.2 Verify preservation tests still pass after all fixes
    - **Property 2: Preservation** - All Preservation Tests Still Pass
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "preservation" -v`
    - **EXPECTED OUTCOME**: All preservation tests PASS (confirms no regressions introduced)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 6.3 Run full backend test suite to check for cross-module regressions
    - Run: `cd backend && pytest -v`
    - **EXPECTED OUTCOME**: All tests pass; no pre-existing tests broken by the three fixes
    - If failures arise, address them before marking this task complete
    - Ask the user if questions arise about intended behavior in edge cases

- [x] 7. Fix Bug 4 — confirmed HubSpot match pointing at a deleted lead (dangling match heal)

  - [x] 7.1 Add a "heal dangling confirmed matches" pass to `run_hubspot_matching`
    - File: `backend/app/tasks/hubspot_tasks.py`, function `run_hubspot_matching`
    - Root cause: `HubSpotMatch.internal_record_id` is a plain Integer with no FK/cascade, so deleting a `Lead` silently orphans any match that pointed at it. The match stays `status='confirmed'` referencing a now-missing lead, so (a) the `matched_deals`/`matched_contacts` skip-set excludes it from re-matching, and (b) `run_enrich_leads_from_hubspot` does `Lead.query.get(<missing id>)` → `None` → `continue`. Net effect: a surviving duplicate lead at the same address (e.g. lead 3415 "2553 N Drake Ave 1" vs deleted lead 916, deal `8749502786` / Gilberto Olivares) never receives the deal stage, the owner/PropertyContact, or the activities.
    - At the START of the function (BEFORE the `matched_deals`/`matched_contacts`/`matched_companies` skip-sets are built), add a healing pass:
      - Query all `HubSpotMatch` rows with `status='confirmed'`, `internal_record_type='lead'`, `internal_record_id IS NOT NULL`.
      - Batch-check which referenced `internal_record_id`s still exist via a single `db.session.query(Lead.id).filter(Lead.id.in_(referenced_ids))` (never N per-row queries).
      - For each match whose referenced lead is MISSING: set `status='pending'` and `internal_record_id=NULL`, then commit. Log: `"run_hubspot_matching: healed N dangling confirmed matches (referenced lead deleted)"`.
    - Because this runs before the skip-sets are built, the healed (now-pending) deal falls through to the existing `match_deal` call and is re-pointed to the surviving lead by address in the same run. `_upsert_match` updates the existing row in place (keyed on `hubspot_record_type` + `hubspot_id`), so no duplicate match row is created.
    - _Bug_Condition: confirmed lead-match whose `internal_record_id` references a Lead that no longer exists_
    - _Expected_Behavior: match reset to pending → re-matched → `internal_record_id` re-points to the surviving duplicate lead; enrichment then links the owner (PropertyContact) and syncs the deal stage label_
    - _Preservation: only matches whose referenced lead is actually missing are touched; confirmed matches with a live lead remain confirmed and untouched (Preservation Test 5), `rejected` matches are never inspected, and company-without-lead behavior is unchanged_
    - _Requirements: 2.4, 2.6, 3.4_

  - [x] 7.2 Write Bug 4 tests that exercise the REAL pipeline functions
    - File: `backend/tests/test_hubspot_sync_bugs.py`
    - Unlike the Bug 2 / Bug 3a exploration tests (which reproduce pipeline logic inline), these call the ACTUAL `run_hubspot_matching` and `run_enrich_leads_from_hubspot`. `create_app` is patched (`patch('app.create_app', return_value=app)`) so the functions' internal `with create_app().app_context()` runs against the in-memory SQLite DB (Flask-SQLAlchemy uses a shared `StaticPool` for in-memory SQLite, so the nested context sees the same data). `HubSpotClientService` is mocked so no live API call is made.
    - `test_bug4_dangling_confirmed_match_relinked_after_lead_deleted` (end-to-end): create lead A at "2553 N Drake Ave" + a confirmed deal match → A, a deal whose `associations.contacts` references Gilberto, a Gilberto contact whose `associations.deals` references the deal, and a contact match with `internal_record_id=NULL`. Delete A, create surviving lead B at the same address (with a keeper lead so SQLite cannot reuse A's id). Run the real `run_hubspot_matching()` + `run_enrich_leads_from_hubspot()`. Assert: the deal match's `internal_record_id == B.id` (single row, not the dead id), a `PropertyContact` links Gilberto to B, and `B.hubspot_deal_stage == "Negotiating Remote"`.
    - `test_bug4_confirmed_match_with_existing_lead_not_rehealed` (preservation guard): a confirmed deal match whose lead STILL EXISTS is left `status='confirmed'` with an unchanged `internal_record_id` after `run_hubspot_matching()`.
    - _Requirements: 2.4, 2.6, 3.4_

  - [x] 7.3 Verify Bug 4 tests pass and no regressions
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug4" -v` → both Bug 4 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` → all 13 tests PASS (exploration + preservation + bug4)
    - Run: `cd backend && pytest -k "hubspot and (match or enrich)" -v` → 37 passed (no regressions in matcher/enrichment)
    - _Requirements: 2.4, 2.6, 3.4_

- [x] 8. Fix Bug 6 — post-import pipeline never auto-advances (stale-session read in the wait loop)

  - [x] 8.1 Force a fresh read each poll in the in-process pipeline thread loop
    - File: `backend/app/services/hubspot_import_service.py`, function `_run_pipeline_after_imports`
    - Root cause: the loop polls `HubSpotImportRun.query.filter(HubSpotImportRun.id.in_(run_ids)).all()` inside a single long-lived SQLAlchemy session. The import tasks update `status` and commit in SEPARATE sessions/processes, but the polling session's identity map keeps returning the STALE status from its first read, so `all(r.status in terminal ...)` never becomes true. The loop spins until the 1-hour `max_wait` timeout and only then runs the pipeline — so (especially with server restarts) the platform almost never auto-syncs after an import.
    - At the TOP of each `while elapsed < max_wait:` iteration, before the `HubSpotImportRun.query...` call, add `db.session.rollback()` followed by `db.session.expire_all()`. Rollback ends the read transaction so the next query starts a fresh snapshot (robust even under REPEATABLE READ); `expire_all()` drops the identity-map cache so attributes reload from the database. On PostgreSQL (READ COMMITTED) the re-query then observes the committed status. `db` is already imported at module top (`from app import db`).
    - Do not change `poll_interval`, `max_wait`, the terminal set, or the `else` timeout fallback — only fix the staleness.
    - _Bug_Condition: polling session's identity map returns stale `status` after the import tasks commit a terminal status in another session_
    - _Expected_Behavior: the loop observes the committed terminal status on the next poll and runs the pipeline promptly via the all-complete path_
    - _Preservation: timeout/`else` fallback and poll cadence unchanged; the loop only reads, so per-iteration rollback is side-effect-free_
    - _Requirements: 3.6_

  - [x] 8.2 Apply the same fresh-read fix to the Celery backup loop
    - File: `backend/celery_worker.py`, task `run_post_import_pipeline`
    - Same stale-identity-map defect in the `while elapsed < max_wait_seconds:` loop. Add `from app import db` in the `with app.app_context():` block (alongside `from app.models import HubSpotImportRun`), then add `db.session.rollback()` + `db.session.expire_all()` at the TOP of each iteration before the query. Keep the timeout `else` branch and cadence intact.
    - _Bug_Condition / Expected_Behavior / Preservation: same as 8.1, for the Celery backup path_
    - _Requirements: 3.6_

  - [x] 8.3 Write Bug 6 regression tests that exercise the REAL loop functions
    - File: `backend/tests/test_hubspot_sync_bugs.py`
    - `test_bug6_inprocess_pipeline_autoadvances_on_committed_status`: creates two `HubSpotImportRun` rows with `status='running'`, patches the five pipeline functions (`run_hubspot_matching`, `run_enrich_leads_from_hubspot`, `run_convert_hubspot_activities`, `run_extract_hubspot_signals`, `run_rescore_leads_after_import`) at their `app.tasks.hubspot_tasks` source, and patches `time.sleep` so its FIRST call commits `status='success'` from a separate-session simulation (raw SQL `UPDATE` with `expire_on_commit` temporarily disabled so the polling session's identity map is not refreshed). Calls the real `_run_pipeline_after_imports(app, run_ids)` and asserts it detected completion promptly (`time.sleep` called at most twice) and ran each pipeline step exactly once via the all-complete path — not the 1-hour timeout fallback.
    - `test_bug6_celery_pipeline_autoadvances_on_committed_status`: same scenario against the real `celery_worker.run_post_import_pipeline`, with `app.create_app` patched to return the test app.
    - Both tests were confirmed to FAIL on unfixed code (the stale identity map kept `status='running'`, so the loop spun to the ~3585s timeout, calling `time.sleep` ~240 times) and PASS after the fix.
    - _Requirements: 3.6_

  - [x] 8.4 Verify Bug 6 tests pass and no regressions
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug6" -v` → both Bug 6 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` → all 15 tests PASS (exploration + preservation + bug4 + bug6)
    - Run: `cd backend && pytest -k "import" -v` → 98 passed (no regressions in import/import-service tests)
    - _Requirements: 3.6_

- [x] 9. Fix Bug 5 — HubSpot activity/task associations stranded on a deleted lead

  - [x] 9.1 Add a "re-point associations stranded on deleted leads" pass to `run_convert_hubspot_activities`
    - File: `backend/app/tasks/hubspot_tasks.py`, function `run_convert_hubspot_activities`
    - Root cause: `InteractionAssociation.target_id` and `TaskAssociation.target_id` are plain Integers with no FK/cascade to `leads`. When a duplicate lead is deleted, its hubspot-imported activity/task associations are left pointing at the now-missing lead, with `Interaction.is_orphaned=False`. The existing orphan re-resolution pass only revisits `is_orphaned=True` rows, and the converter is idempotent, so these historical activities/tasks stay stranded on the dead lead and never appear on the surviving lead. Concrete case: lead 3415 (2553 N Drake) — ~20 interactions (3 notes + 17 calls) and 24 task associations remained on deleted lead 916 even after Bug 4 re-pointed the deal match to 3415.
    - Added a new pass AFTER the existing orphan re-resolution pass:
      - INTERACTIONS: find `InteractionAssociation` rows with `target_type='lead'` whose `target_id` references a missing lead, scoped to `source='hubspot_import'` interactions with a non-null `hubspot_engagement_id`. A single batched existence check (collect distinct lead target_ids → one `Lead.id.in_(...)` query → existing set → missing set) avoids N+1. For each affected interaction (deduped), re-resolve via `converter._resolve_associations_by_engagement_id(interaction.hubspot_engagement_id)`. If it returns association(s): delete the row(s) pointing at the missing lead, add the resolved targets (deduped), leave `is_orphaned=False`. If it returns nothing: set `is_orphaned=True` so the orphan pass revisits it later (no data dropped).
      - TASKS: same approach for `TaskAssociation` rows with `target_type='lead'` pointing at a missing lead, scoped to hubspot-imported tasks (`hubspot_task_id` non-null). The Task's `hubspot_task_id` is the engagement id — reuse `converter._resolve_associations_by_engagement_id(task.hubspot_task_id)`, keep only `('lead','organization')` targets (mirrors `convert_task`), and re-point the dangling association (deduped).
      - Incremental commit with try/except per record, mirroring the orphan pass (counts `re_pointed`/errors, rollback on error, summary log line).
    - _Bug_Condition: a hubspot-imported activity/task association whose `target_type='lead'` `target_id` references a Lead that no longer exists_
    - _Expected_Behavior: the dangling association is replaced with the resolved current lead (via the Bug-4-healed deal/contact match), so the activity/task surfaces on the surviving lead_
    - _Preservation: only associations whose target lead is actually missing are touched; associations pointing at a live lead are untouched; manually-created interactions/tasks (no `hubspot_engagement_id`/`hubspot_task_id`) are never touched; the pass is idempotent — a second run is a no-op_
    - _Requirements: 2.7, 2.8, 3.4_

  - [x] 9.2 Write Bug 5 tests that exercise the REAL `run_convert_hubspot_activities`
    - File: `backend/tests/test_hubspot_sync_bugs.py`, class `TestBug5StrandedAssociation`
    - These call the ACTUAL `run_convert_hubspot_activities` via `patch('app.create_app', return_value=app)` (same pattern as the Bug 4 / Bug 6 tests). A missing lead is simulated with `target_id=9999999` (the stranded state left after the original lead was deleted).
    - `test_bug5_interaction_association_stranded_on_deleted_lead_relinked`: surviving lead B + confirmed deal match → B + CALL engagement; an already-converted `Interaction(source='hubspot_import', is_orphaned=False)` whose only `InteractionAssociation(target_type='lead')` points at the missing id. After the real run: the dangling association is gone, a new association to `B.id` exists, `is_orphaned` stays False. Also asserts idempotency by running the pass twice (exactly one lead association, stable `target_id`).
    - `test_bug5_task_association_stranded_on_deleted_lead_relinked`: analogous for a `Task(hubspot_task_id set)` + `TaskAssociation(target_type='lead', target_id=missing)` → re-pointed to B, no duplicate.
    - `test_bug5_association_with_existing_lead_untouched` (preservation guard): an interaction associated to an EXISTING lead is left unchanged (target_id unchanged, no duplicate, `is_orphaned` unchanged).
    - _Requirements: 2.7, 2.8, 3.4_

  - [x] 9.3 Verify Bug 5 tests pass and no regressions
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug5" -v` → 3 Bug 5 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` → all 18 tests PASS (exploration + preservation + bug4 + bug6 + bug5)
    - Run: `cd backend && pytest -k "hubspot and (convert or activit or interaction or task)" -v` → 25 passed (no regressions in activity/conversion/interaction/task tests)
    - _Requirements: 2.7, 2.8, 3.4_

- [x] 10. Bug 7 — prevent orphaned HubSpot refs on lead delete (ORM delete-time cleanup hook)

  - [x] 10.1 Add a `before_delete` cleanup hook on the `Lead` model
    - File: `backend/app/models/lead.py` (registered at module level via `@event.listens_for(Property, 'before_delete')`, so it covers the `Lead`/`Property` alias)
    - Root cause: `HubSpotMatch.internal_record_id`, `InteractionAssociation.target_id`, and `TaskAssociation.target_id` are POLYMORPHIC — each id column is paired with a `*_type` discriminator ('lead' vs 'organization'/'contact'), so it may reference a lead OR another entity. A SQL foreign key / `ON DELETE CASCADE` can only target one parent table, so it cannot be used. A SQLAlchemy `before_delete` mapper event is the right mechanism for the app's own ORM deletes (`session.delete(lead)`).
    - The listener receives `(mapper, connection, target)` and runs mid-flush, so it issues Core statements through `connection` against the models' `__table__` constructs (NOT ORM session ops, NOT hardcoded table-name strings — real table/column names are resolved from model metadata). Guard: returns immediately if `target.id is None`. For the lead being deleted:
      - 1. `HubSpotMatch.__table__.update()` WHERE `internal_record_type='lead'` AND `internal_record_id=target.id` AND `status IN ('confirmed','pending')` → SET `status='pending'`, `internal_record_id=NULL`. `rejected` matches are deliberately excluded so reviewer decisions are preserved.
      - 2. `Interaction.__table__.update()` SET `is_orphaned=True` WHERE `id IN (SELECT interaction_id FROM interaction_associations WHERE target_type='lead' AND target_id=target.id)` (Core `select(...)` subquery; `.values(is_orphaned=True)` so the boolean literal renders on both SQLite and PostgreSQL) — run BEFORE deleting the associations — then `InteractionAssociation.__table__.delete()` WHERE `target_type='lead'` AND `target_id=target.id`. The interaction rows themselves are preserved.
      - 3. `TaskAssociation.__table__.delete()` WHERE `target_type='lead'` AND `target_id=target.id`. The task rows themselves are preserved.
    - LIMITATION (documented in a comment): this hook fires only for ORM `session.delete(lead)`; it does NOT fire for bulk `Query.delete()` or raw SQL deletes (which bypass the unit of work). The Bug 4 / Bug 5 sync-time healing in `run_hubspot_matching` / `run_convert_hubspot_activities` remains the catch-all safety net for those bulk/SQL/manual deletions.
    - _Bug_Condition: a Lead is deleted via the ORM while polymorphic HubSpot references (match / interaction association / task association) still point at it_
    - _Expected_Behavior: the lead's confirmed/pending matches reset to pending+NULL (re-matchable later), its interactions are orphaned + de-associated, and its task associations are removed — no dangling references survive_
    - _Preservation: `rejected` matches and all records belonging to other leads are untouched; interaction/task rows are preserved (only re-flagged/de-associated)_
    - _Requirements: 2.4, 2.7, 2.8, 3.4_

  - [x] 10.2 Write Bug 7 tests that exercise a REAL ORM lead delete
    - File: `backend/tests/test_hubspot_sync_bugs.py`, class `TestBug7LeadDeleteCleanup`
    - These drive an actual `db.session.delete(lead); db.session.commit()` so the `before_delete` hook fires (no pipeline mocking needed).
    - `test_lead_delete_resets_matches_and_orphans_activities`: a lead with a `confirmed` `HubSpotMatch`, a `hubspot_import` `Interaction` + `InteractionAssociation(target_type='lead')`, and a `Task(hubspot_task_id=...)` + `TaskAssociation(target_type='lead')`. After deleting the lead: the match row is `status='pending'` with `internal_record_id IS NULL`; the interaction is preserved with `is_orphaned=True` and its association is gone; the task is preserved and its association is gone.
    - `test_lead_delete_preserves_rejected_match_and_other_leads`: a `rejected` match on the deleted lead stays `rejected` (and keeps its `internal_record_id`); a confirmed match + interaction/task associations belonging to a DIFFERENT surviving lead are untouched.
    - _Requirements: 2.4, 2.7, 2.8, 3.4_

  - [x] 10.3 Verify Bug 7 tests pass and no regressions
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "Bug7" -v` → both Bug 7 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` → all 20 tests PASS (exploration + preservation + bug4 + bug6 + bug5 + bug7)
    - Run: `cd backend && pytest -k "lead or hubspot or admin or import" -q` → 682 passed (no regressions; the hook fires on the ORM lead deletes used across the suite)
    - _Requirements: 2.4, 2.7, 2.8, 3.4_

- [x] 11. Bug 8 — rescore on every change (lead_score parity with recommended_action)

  - [x] 11.1 Add a unified per-lead refresh helper
    - File: `backend/app/services/lead_refresh.py` — new function `refresh_lead_scoring(lead_id: int) -> None`
    - Root cause: `recommended_action` was recomputed at most mutation points (via `ActionEngineService.recompute_and_persist`), but `lead_score` was only recomputed by the post-import rescore, the webhook signal-extraction chain, and the nightly bulk job — NOT on manual status changes, lead/property field edits, enrichment, or contact link/unlink. So `lead_score` went stale (e.g. a status flip to `negotiating_remote` did not apply the +25 stage bonus) until a bulk rescore ran.
    - The helper recomputes AND persists BOTH fields for a single lead: (1) resolves the owner's weights via `LeadScoringEngine.get_weights(lead.owner_user_id or 'default')`, loads the lead's `HubSpotSignal` rows ordered by `extracted_at asc`, calls `LeadScoringEngine.compute_score(lead, weights, signals=...)`, and persists to `lead.lead_score` (mirrors `LeadScoringEngine.bulk_rescore._rescore_lead` for one lead — no duplicated scoring logic); then (2) calls `ActionEngineService.recompute_and_persist(lead_id)`. Score is committed first so score-threshold action rules (e.g. `lead_score >= 70` → `ready_for_outreach`) see the fresh score.
    - Fully error-isolated: wrapped in try/except, logs a warning on failure, and rolls back only its OWN uncommitted work — it NEVER raises into the caller, so a scoring failure cannot break the user's underlying mutation (which is committed before the helper runs). Synchronous (single lead = cheap); does NOT enqueue Celery.
    - _Bug_Condition: a non-HubSpot mutation changes a scoring input (stage bonus, data completeness, owner situation, open-task count) but `lead_score` is not recomputed, going stale_
    - _Expected_Behavior: both `lead_score` and `recommended_action` are refreshed in parity, immediately, at the mutation point_
    - _Preservation: HubSpot import/webhook/nightly bulk rescore paths are untouched; the helper reuses existing engine APIs and never raises into callers_
    - _Requirements: 3.6_

  - [x] 11.2 Call the helper at every non-HubSpot mutation point (synchronously, after the change commits)
    - `backend/app/controllers/command_center_controller.py`:
      - `_rescore_after_status_change` refactored to delegate to `refresh_lead_scoring` (was bulk_rescore + separate action recompute) — covers `update_status`, `do_not_contact`, `park`, `reactivate`, `suppress`. This is the key one: a status change now applies the +25 stage bonus to `lead_score`.
      - `create_task`, `update_task` (snooze + inline title/due edit), `complete_task` — refresh after the change so open-task-count-driven action AND score stay current.
    - `backend/app/controllers/task_controller.py`: `create_task`, `update_task`, `complete_task` — new `_refresh_associated_leads(task)` helper refreshes every lead the Task touches (direct `lead_id` FK and/or `target_type='lead'` associations).
    - `backend/app/services/data_source_connector.py` `enrich_lead` — refresh on the success path after the enrichment commit (covers both the single-lead enrich endpoint and the bulk enrich path), since enrichment changes data-completeness / owner-situation sub-scores.
    - `backend/app/services/contact_service.py` `link_contact_to_property` / `unlink_contact_from_property` — refresh the affected property (`property_id` is the lead id), since linking/unlinking an owner contact changes data-completeness and owner-situation. (The HubSpot matcher creates `PropertyContact` rows directly, NOT via this service, so the import path stays untouched.)
    - `backend/app/services/lead_kanban_service.py` `move_lead` — refresh after the pipeline-stage move commit (a kanban stage move is a non-HubSpot status mutation that also changes the stage bonus).
    - No dedicated lead/property field-edit endpoint exists in the codebase today (field facts are written via enrichment / import / HubSpot sync); the helper is the integration point a future field-edit endpoint would call, and is covered directly by a test.
    - _Requirements: 3.6_

  - [x] 11.3 Fix `LeadTimelineEntry` → `Lead` delete cascade (supporting fix surfaced by 11.2)
    - File: `backend/app/models/lead_timeline_entry.py`
    - The `recommended_action_changed` timeline entry created by `recompute_and_persist` (now also fired on contact link, etc.) exposed a latent bug: the `timeline_entries` backref had no cascade, so deleting a `Lead` via the ORM tried to NULL the NOT NULL `lead_id` FK (`IntegrityError`). Added `cascade='all, delete-orphan'` to the backref (mirroring `Lead.audit_trail`); the FK already declared `ondelete='CASCADE'` for the DB layer, so this aligns the ORM with the DB and makes lead deletion delete its timeline entries instead of erroring.
    - _Preservation: no path relied on the prior (erroring) nullify behavior; deleting a lead now removes its timeline entries in both SQLite (ORM cascade) and PostgreSQL (DB cascade)_
    - _Requirements: 3.6_

  - [x] 11.4 Write Bug 8 tests and verify
    - File: `backend/tests/test_hubspot_sync_bugs.py`, class `TestBug8RescoreOnChange` — drives the REAL controller endpoints / services and the helper directly against the in-memory DB (no inline scoring logic):
      - `test_bug8_status_change_rescores_stage_bonus`: a manual status change to `negotiating_remote` via the real `/status` endpoint raises `lead_score` by exactly the +25 stage bonus over the 0-bonus baseline.
      - `test_bug8_enrichment_increases_lead_score`: a real `DataSourceConnector.enrich_lead` that fills score-relevant fields increases `lead_score`.
      - `test_bug8_field_edit_recomputes_score`: editing a scoring input then calling the helper (as a field-edit endpoint would) recomputes the score.
      - `test_bug8_task_create_and_complete_refresh_action_and_score`: creating then completing a task via the real command-center endpoints refreshes `recommended_action` (create → `nurture`, complete → `create_task`) AND recomputes the stale `lead_score` sentinel.
      - `test_bug8_scoring_error_isolated_status_change_still_commits`: with the scoring engine patched to raise, the status-change endpoint still returns 200 and the new status is committed (error isolation).
      - `test_bug8_refresh_helper_swallows_engine_error`: `refresh_lead_scoring` returns None (never raises) when the engine raises, leaving the caller's committed work intact.
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug8 or Bug8" -v` → 6 Bug 8 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` → all 26 tests PASS (exploration + preservation + bug4 + bug6 + bug5 + bug7 + bug8)
    - Regression sweep on touched controllers/services (command_center, task, enrich, lead, action_engine, scoring) → all green (the `LeadTimelineEntry` cascade fix resolved the only failure, in `test_contact_properties`).
    - _Requirements: 3.6_

- [x] 12. Bug 9 — signal de-duplication + minor no-interest status penalty

  - [x] 12.1 Fix A — de-duplicate signal adjustments in `compute_score`
    - File: `backend/app/services/lead_scoring_engine.py`, method `LeadScoringEngine.compute_score`
    - Root cause: the signal loop summed `SIGNAL_ADJUSTMENTS` PER ROW, so duplicate `HubSpotSignal` rows of the same `signal_type` stacked. A lead with five re-extracted `PRIOR_WARM_CONVERSATION` rows got +75 instead of +15, pushing a data-thin "no interest" lead (Linda, 91.9) above an actively-negotiating lead (Juan, 70.7).
    - Changed the loop to collect the SET of recognised `signal_type`s present, then add each type's adjustment exactly ONCE. Signals are boolean STATES, not counters — dedup is WITHIN a type; DISTINCT types still each apply. Still accepts both `HubSpotSignal` instances and plain strings (same `signal_type` extraction as before). `compute_recommended_action` is unchanged (it already picks by priority).
    - _Bug_Condition: multiple HubSpotSignal rows of the SAME signal_type for a lead (e.g. the same signal re-extracted across sync runs)_
    - _Expected_Behavior: each distinct signal_type contributes its adjustment at most once (e.g. five PRIOR_WARM_CONVERSATION rows => +15, not +75)_
    - _Preservation: distinct-type signals still stack (PRIOR_WARM_CONVERSATION +15 AND OFFER_PREVIOUSLY_SENT +10 => +25); suppression cap, [0,100] clamp, and string/instance handling unchanged_
    - _Requirements: 2.4_

  - [x] 12.2 Fix B — minor no-interest status penalty in `_pipeline_stage_bonus`
    - File: `backend/app/services/lead_scoring_engine.py`, method `LeadScoringEngine._pipeline_stage_bonus`
    - Changed the `STAGE_BONUS` entry for `'mailing_contacted_no_interest'` from `+5.0` to `-10.0`, and updated the docstring stage-bonus table to document the new value and rationale: explicit "no interest" should rank slightly BELOW an uncontacted lead (`mailing_no_contact_made`, baseline 0), instead of being rewarded for having been reached.
    - All other stage bonuses are unchanged, and the `SELLER_NOT_INTERESTED` signal adjustment (-40) is unchanged.
    - _Bug_Condition: a 'mailing_contacted_no_interest' lead earned a net-positive +5 stage bonus, so explicit disinterest helped its score_
    - _Expected_Behavior: 'mailing_contacted_no_interest' now yields -10.0, ranking a no-interest lead just below an uncontacted (0-bonus) one_
    - _Preservation: every other STAGE_BONUS entry and the SELLER_NOT_INTERESTED (-40) signal are untouched_
    - _Requirements: 2.4_

  - [x] 12.3 Fix C — make signal extraction idempotent (stop writing duplicate rows)
    - File: `backend/app/services/hubspot_signal_extractor_service.py`, method `HubSpotSignalExtractorService.extract_signals` (+ new helper `_signal_already_exists`)
    - Investigated the model + all persistence paths: `HubSpotSignal` (`backend/app/models/hubspot_signal.py`) has a `source_engagement_id` String column. Signals are persisted in THREE places, all of which call `extract_signals(...)` then `db.session.add(signal)`: the inline `_extract_signals_for_interaction` in `hubspot_activity_converter_service.py`, the pipeline `run_extract_hubspot_signals` in `hubspot_tasks.py`, and the webhook `run_extract_incremental_signals` in `hubspot_webhook_tasks.py`. All three set `source_engagement_id` to the engagement id, so centralizing the dedup inside `extract_signals` fixes every path at once.
    - **Chosen dedup key: `(lead_id, signal_type, source_engagement_id)`** (documented in `_signal_already_exists`). Before emitting an extracted signal, `extract_signals` now skips it when an equivalent row already exists for that key — so re-extraction across sync runs no longer accumulates duplicates. Distinct sources (different `source_engagement_id`) and distinct types still create distinct rows; only re-extraction of the SAME signal is skipped. When `source_engagement_id` is None the key naturally degrades to `(lead_id, signal_type)` (one sourceless row per type per lead) — noted in the docstring.
    - _Bug_Condition: the same signal (same lead, type, source engagement) re-extracted on a later sync run inserts another HubSpotSignal row_
    - _Expected_Behavior: re-extraction is a no-op for an already-present (lead_id, signal_type, source_engagement_id); the row count for that key stays at 1_
    - _Preservation: first-time extraction is unchanged; distinct sources/types still produce distinct rows; FOLLOW_UP_OVERDUE and suppression handling unchanged_
    - _Requirements: 2.4_

  - [x] 12.4 Write Bug 9 tests (class `TestBug9SignalDedupAndNoInterest`)
    - File: `backend/tests/test_hubspot_sync_bugs.py` — drive the REAL `LeadScoringEngine` and `HubSpotSignalExtractorService` (no inline scoring logic).
    - `test_bug9_compute_score_dedups_same_signal_type`: five PRIOR_WARM_CONVERSATION signals score identically to one (== baseline + 15, not +75).
    - `test_bug9_distinct_signal_types_still_stack`: PRIOR_WARM_CONVERSATION (+15) AND OFFER_PREVIOUSLY_SENT (+10) together add +25 — dedup is within a type, not across.
    - `test_bug9_no_interest_status_minor_penalty`: `_pipeline_stage_bonus` returns -10.0 for `mailing_contacted_no_interest`; a lead in that status scores exactly 10 points below the same lead in `mailing_no_contact_made`.
    - `test_bug9_ranking_no_interest_below_negotiating`: Lead L (no-interest, thin data, five duplicate warm rows) vs Lead J (negotiating, slightly better data, one warm row) — after `compute_score`, J > L (the dedup + penalty correct the real-world inversion; under the old code L outranked J).
    - `test_bug9_extraction_dedup_idempotent`: extract + persist the same signal for the same lead+source twice via the real extractor — exactly ONE row remains for the `(lead_id, signal_type, source_engagement_id)` key.
    - _Requirements: 2.4_

  - [x] 12.5 Verify Bug 9 fixes and no regressions
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -k "bug9 or Bug9" -v` -> 5 Bug 9 tests PASS
    - Run: `cd backend && pytest tests/test_hubspot_sync_bugs.py -v` -> all 31 tests PASS (exploration + preservation + bug4 + bug6 + bug5 + bug7 + bug8 + bug9)
    - Regression sweep: `cd backend && pytest -k "scoring or signal or hubspot or action_engine" -q` -> 438 passed, 1666 deselected (no regressions). No prior test assumed stacked same-type signal scores — `test_lead_scoring_engine.py`'s same-type stacking tests only assert the [0,100] clamp bounds, and exact-value tests use distinct types, so all stayed green without edits.
    - _Requirements: 2.4_
