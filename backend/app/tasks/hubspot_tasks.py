"""HubSpot CRM Migration — Celery task implementations.

All nine tasks are defined here as pure functions that are registered on the
existing Celery app in ``celery_worker.py``.  This module contains NO
``@celery.task`` decorators — those live in ``celery_worker.py`` where the
``celery`` app instance is guaranteed to exist.

Entry points (called by the decorated wrappers in celery_worker.py):
  run_import_hubspot_deals(run_id)
  run_import_hubspot_contacts(run_id)
  run_import_hubspot_companies(run_id)
  run_import_hubspot_engagements(run_id)
  run_hubspot_matching(run_id)
  run_convert_hubspot_activities(run_id)
  run_extract_hubspot_signals(run_id)
  run_rescore_leads_after_import(user_id)
  run_generate_backup_export()

Requirements: 7.6, 7.7, 7.8, 8.1, 8.2, 8.3, 8.4, 8.6, 9.4, 20.2, 20.3
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Signal types that mark a lead as warm (used in run_extract_hubspot_signals)
WARM_SIGNAL_TYPES = frozenset({'PRIOR_WARM_CONVERSATION', 'APPOINTMENT_OCCURRED'})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _fetch_deal_contact_associations_with_retry(
    client, deal_id: str, *, max_attempts: int = 3, base_delay: float = 1.0,
) -> list:
    """Fetch one deal's contact associations via the v4 batch API with bounded
    retry + exponential backoff on *transient* HubSpot failures.

    HubSpot rate limits (429) and server/timeout errors surface as
    ``HubSpotRateLimitError`` / ``ExternalServiceError`` from the client. Those
    are retried up to ``max_attempts`` times, honouring a server-provided
    ``Retry-After`` when present. A non-transient error, or a final exhausted
    retry, is logged and reported as an empty list so a flaky association fetch
    degrades gracefully instead of aborting enrichment — consistent with the
    surrounding best-effort error handling.

    Returns the list of associated contact-id strings (possibly empty).
    """
    from app.exceptions import ExternalServiceError, HubSpotRateLimitError

    transient = (HubSpotRateLimitError, ExternalServiceError)
    for attempt in range(1, max_attempts + 1):
        try:
            # allow_partial=False so a transient failure on this single-deal
            # batch is RAISED into the backoff loop below instead of being
            # swallowed by the client and returned as an empty/partial result —
            # otherwise the retry never actually retries.
            assoc_map = client.fetch_deal_contact_associations(
                [deal_id], allow_partial=False
            )
            return assoc_map.get(deal_id, [])
        except transient as exc:
            if attempt >= max_attempts:
                logger.warning(
                    "v4 deal->contact association fetch for deal %s failed after "
                    "%d attempts: %s", deal_id, attempt, exc,
                )
                return []
            payload = getattr(exc, 'payload', None) or {}
            retry_after = payload.get('retry_after')
            # Honour an explicit Retry-After even when it is 0 — `if retry_after`
            # would treat a legitimate zero-second delay as "missing" and fall
            # back to exponential backoff.
            delay = (
                float(retry_after) if retry_after is not None
                else base_delay * (2 ** (attempt - 1))
            )
            logger.warning(
                "v4 deal->contact association fetch for deal %s failed "
                "(attempt %d/%d), retrying in %.1fs: %s",
                deal_id, attempt, max_attempts, delay, exc,
            )
            time.sleep(delay)
        except Exception as exc:
            # Non-transient (auth / programming) error — don't hammer the API.
            logger.warning(
                "v4 deal->contact association fetch for deal %s failed "
                "(non-retryable): %s", deal_id, exc,
            )
            return []
    return []


def _mark_run_failed(db, run, message: str) -> None:
    """Mark an ImportRun as failed with an error message."""
    run.status = 'failed'
    run.end_time = datetime.utcnow()
    run.error_message = message
    db.session.commit()


def _mark_run_complete(db, run, error_count: int) -> None:
    """Mark an ImportRun as success or partial depending on error_count."""
    run.status = 'partial' if error_count > 0 else 'success'
    run.end_time = datetime.utcnow()
    db.session.commit()


def _upsert_hubspot_record(db, model_class, hubspot_id: str,
                           raw_payload: dict, run_id: int,
                           extra_values: dict = None) -> str:
    """
    UPSERT a single HubSpot record using PostgreSQL INSERT ... ON CONFLICT DO UPDATE.

    Preserves ``first_imported_at`` on conflict (never overwritten).
    Updates ``raw_payload``, ``last_updated_at``, and ``import_run_id`` on conflict.

    Returns 'inserted' if a new row was created, 'updated' if an existing row was updated.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.utcnow()
    values = {
        'hubspot_id': hubspot_id,
        'raw_payload': raw_payload,
        'import_run_id': run_id,
        'first_imported_at': now,
        'last_updated_at': now,
    }
    if extra_values:
        values.update(extra_values)

    stmt = pg_insert(model_class.__table__).values(**values)

    update_set = {
        'raw_payload': stmt.excluded.raw_payload,
        'last_updated_at': stmt.excluded.last_updated_at,
        'import_run_id': stmt.excluded.import_run_id,
        # first_imported_at is intentionally NOT updated — preserves original import time
    }
    if extra_values:
        for key in extra_values:
            if key != 'first_imported_at':
                update_set[key] = stmt.excluded[key]

    stmt = stmt.on_conflict_do_update(
        index_elements=['hubspot_id'],
        set_=update_set,
    )
    # Add RETURNING xmax so we can distinguish INSERT (xmax=0) from UPDATE (xmax>0).
    # This is the only reliable way to detect insert vs update with ON CONFLICT DO UPDATE
    # in PostgreSQL — inserted_primary_key is unreliable for this purpose.
    stmt = stmt.returning(model_class.__table__.c['id'], db.literal_column('xmax'))

    row = db.session.execute(stmt).fetchone()
    # xmax == 0 means the row was freshly inserted; non-zero means it was updated
    if row is not None and int(row[1]) == 0:
        return 'inserted'
    return 'updated'


# ---------------------------------------------------------------------------
# Generic import runner (shared by all four import tasks)
# ---------------------------------------------------------------------------

def _run_import_generic(
    run_id: int,
    object_type: str,
    model_class_name: str,
    fetch_method_name: str,
    self_task=None,
    extra_value_extractor=None,
    id_extractor=None,
):
    """
    Generic paginated import for deals, contacts, companies, and engagements.

    Args:
        run_id: HubSpotImportRun primary key.
        object_type: Human-readable label for logging ('deals', 'contacts', etc.).
        model_class_name: String name of the SQLAlchemy model class (resolved inside
            the app context to avoid importing outside of it).
        fetch_method_name: Name of the HubSpotClientService method to call.
        self_task: Bound Celery task instance (for retry support).
        extra_value_extractor: Optional callable(record) -> dict of extra column values.
        id_extractor: Optional callable(record) -> str to extract the HubSpot ID.
            Defaults to ``str(record.get('id', ''))``. Use this for APIs that nest
            the ID (e.g. legacy engagements API: ``record['engagement']['id']``).
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        import app.models as _models
        from app import db
        from app.models import HubSpotImportRun, HubSpotConfig
        from app.services import HubSpotClientService
        from app.exceptions import HubSpotRateLimitError, ExternalServiceError

        model_class = getattr(_models, model_class_name)

        # Load the import run
        run = HubSpotImportRun.query.get(run_id)
        if run is None:
            logger.error("_run_import_generic: run_id=%d not found for %s", run_id, object_type)
            return

        # Load HubSpot config
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            _mark_run_failed(db, run, "No HubSpot configuration found")
            logger.error("_run_import_generic: no HubSpotConfig found for run_id=%d", run_id)
            return

        client = HubSpotClientService(config)
        fetch_method = getattr(client, fetch_method_name)

        created_count = 0
        updated_count = 0
        error_count = 0
        total_fetched = 0

        try:
            for record in fetch_method():
                total_fetched += 1
                try:
                    hubspot_id = id_extractor(record) if id_extractor else str(record.get('id', ''))
                    if not hubspot_id:
                        logger.warning(
                            "_run_import_generic: %s record missing id, skipping", object_type
                        )
                        error_count += 1
                        continue

                    extra_values = extra_value_extractor(record) if extra_value_extractor else None

                    outcome = _upsert_hubspot_record(
                        db=db,
                        model_class=model_class,
                        hubspot_id=hubspot_id,
                        raw_payload=record,
                        run_id=run_id,
                        extra_values=extra_values,
                    )
                    db.session.commit()

                    if outcome == 'inserted':
                        created_count += 1
                    else:
                        updated_count += 1

                    # Update run counts after each record for accuracy
                    run.total_fetched = total_fetched
                    run.created_count = created_count
                    run.updated_count = updated_count
                    run.error_count = error_count
                    db.session.commit()

                except (HubSpotRateLimitError, ExternalServiceError):
                    raise  # Let the outer handler deal with retryable errors
                except Exception as record_exc:
                    # Non-fatal record error: log, increment error_count, continue
                    logger.warning(
                        "_run_import_generic: non-fatal error on %s record hubspot_id=%s: %s",
                        object_type, record.get('id', 'unknown'), record_exc,
                    )
                    error_count += 1
                    run.error_count = error_count
                    db.session.commit()

        except (HubSpotRateLimitError, ExternalServiceError) as retryable_exc:
            # Retryable error — let Celery retry with exponential backoff
            logger.warning(
                "_run_import_generic: retryable error for %s run_id=%d: %s",
                object_type, run_id, retryable_exc,
            )
            if self_task is not None:
                raise self_task.retry(
                    exc=retryable_exc,
                    countdown=2 ** self_task.request.retries * 60,
                )
            raise

        except Exception as fatal_exc:
            # Fatal error — mark run as failed and stop
            logger.error(
                "_run_import_generic: fatal error for %s run_id=%d: %s",
                object_type, run_id, fatal_exc, exc_info=True,
            )
            _mark_run_failed(db, run, str(fatal_exc))
            raise

        # All records processed — finalize run
        run.total_fetched = total_fetched
        run.created_count = created_count
        run.updated_count = updated_count
        run.error_count = error_count
        _mark_run_complete(db, run, error_count)

        logger.info(
            "_run_import_generic: %s run_id=%d complete — "
            "total=%d created=%d updated=%d errors=%d status=%s",
            object_type, run_id, total_fetched, created_count, updated_count,
            error_count, run.status,
        )


# ---------------------------------------------------------------------------
# Task 1: import_hubspot_deals
# ---------------------------------------------------------------------------

def run_import_hubspot_deals(run_id: int, self_task=None) -> None:
    """Paginate and UPSERT all HubSpot deals into hubspot_deals, then
    backfill contact associations via the v4 batch API.

    The CRM v3 list endpoint silently returns an empty ``associations`` block
    for all deals, so we run a separate v4 batch read after the import to
    populate ``raw_payload["associations"]["contacts"]`` for every deal.

    Requirements: 7.6, 7.7, 7.8, 8.1, 8.6, 20.2, 20.3
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()

    # Step 1 — standard paginated import (stores deals without associations)
    _run_import_generic(
        run_id=run_id,
        object_type='deals',
        model_class_name='HubSpotDeal',
        fetch_method_name='fetch_all_deals',
        self_task=self_task,
    )

    # Step 2 — backfill contact associations via v4 batch API
    with app.app_context():
        from app import db
        from app.models import HubSpotDeal, HubSpotConfig, HubSpotImportRun
        from app.services.hubspot_client_service import HubSpotClientService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            logger.warning(
                "run_import_hubspot_deals: skipping association backfill — no HubSpotConfig"
            )
            return

        try:
            _backfill_deal_contact_associations(app, db, HubSpotClientService(config))
            _check_association_health(db, 'deals', run_id)
        except Exception as exc:
            logger.error(
                "run_import_hubspot_deals: association backfill failed for run_id=%d: %s",
                run_id, exc, exc_info=True,
            )
            run = HubSpotImportRun.query.get(run_id)
            if run:
                run.status = 'partial'
                run.error_message = f"Association backfill failed: {exc}"
                db.session.commit()
            raise


def _backfill_deal_contact_associations(app, db, client) -> None:
    """Fetch contact associations for all deals via the v4 batch API and
    merge them into each deal's ``raw_payload["associations"]["contacts"]``.

    Safe to call multiple times — existing contact IDs in the payload are
    preserved; new ones from HubSpot are merged in.

    Processes deals in batches of 100 (the v4 API limit).
    """
    from app.models import HubSpotDeal
    from app.services.hubspot_client_service import HubSpotClientService

    all_deals = HubSpotDeal.query.all()
    deal_ids = [d.hubspot_id for d in all_deals]
    id_to_deal = {d.hubspot_id: d for d in all_deals}

    if not deal_ids:
        logger.info("_backfill_deal_contact_associations: no deals to process")
        return

    logger.info(
        "_backfill_deal_contact_associations: fetching associations for %d deals",
        len(deal_ids),
    )

    try:
        assoc_map = client.fetch_deal_contact_associations(deal_ids)
    except Exception as exc:
        logger.error(
            "_backfill_deal_contact_associations: failed to fetch associations: %s", exc
        )
        raise

    updated = 0
    for deal_id, contact_ids in assoc_map.items():
        deal = id_to_deal.get(deal_id)
        if deal is None:
            continue
        if not contact_ids:
            continue

        # Merge into raw_payload["associations"]["contacts"]["results"]
        # Preserve any existing entries; add new ones.
        payload = dict(deal.raw_payload or {})
        assoc = dict(payload.get("associations", {}))
        contacts_block = dict(assoc.get("contacts", {}))
        existing_results = list(contacts_block.get("results", []))
        existing_ids = {str(r.get("id", "")) for r in existing_results}

        new_results = list(existing_results)
        for cid in contact_ids:
            if cid not in existing_ids:
                new_results.append({"id": cid, "type": "deal_to_contact"})
                existing_ids.add(cid)

        if len(new_results) == len(existing_results):
            # Nothing new — skip the write
            continue

        contacts_block["results"] = new_results
        assoc["contacts"] = contacts_block
        payload["associations"] = assoc
        deal.raw_payload = payload
        db.session.add(deal)
        updated += 1

        # Commit in batches of 100 to avoid a huge single transaction
        if updated % 100 == 0:
            db.session.commit()
            logger.debug(
                "_backfill_deal_contact_associations: committed %d updates so far", updated
            )

    db.session.commit()
    logger.info(
        "_backfill_deal_contact_associations: complete — %d deals updated with contact associations",
        updated,
    )


# ---------------------------------------------------------------------------
# Task 2: import_hubspot_contacts
# ---------------------------------------------------------------------------

def _check_association_health(db, object_type: str, run_id: int) -> None:
    """After a backfill, check what fraction of records still have empty associations.

    If >90% of records have no associations populated, the import run is marked
    ``partial`` with an explanatory warning so operators can see the gap in the
    import run history rather than a misleading ``success``.

    Args:
        object_type: ``'deals'`` or ``'contacts'`` — used to select the model and
            the association key to inspect.
        run_id:      The ``HubSpotImportRun.id`` to update if the check fails.
    """
    import app.models as _models
    from app.models import HubSpotImportRun

    model_name = 'HubSpotDeal' if object_type == 'deals' else 'HubSpotContact'
    assoc_key = 'contacts' if object_type == 'deals' else 'deals'
    model_class = getattr(_models, model_name)

    total = model_class.query.filter_by(import_run_id=run_id).count()
    if total == 0:
        return

    # Count records where associations.<assoc_key>.results is a non-empty array.
    # We do this in Python rather than SQL to avoid JSON operator dialect differences.
    all_records = model_class.query.filter_by(import_run_id=run_id).all()
    populated = 0
    for record in all_records:
        assoc = (record.raw_payload or {}).get('associations', {})
        block = assoc.get(assoc_key, {})
        if isinstance(block, dict) and block.get('results'):
            populated += 1

    empty_pct = (total - populated) / total * 100
    logger.info(
        "_check_association_health: %s — %d/%d records have %s associations populated "
        "(%.1f%% empty)",
        object_type, populated, total, assoc_key, empty_pct,
    )

    if empty_pct > 90:
        run = HubSpotImportRun.query.get(run_id)
        if run and run.status == 'success':
            warning = (
                f"Association backfill: {populated}/{total} {object_type} records have "
                f"{assoc_key} associations populated after v4 batch fetch "
                f"({empty_pct:.0f}% still empty). "
                f"The HubSpot v4 associations API may be returning incomplete data."
            )
            run.status = 'partial'
            run.error_message = warning
            db.session.commit()
            logger.warning(
                "_check_association_health: marked run_id=%d as partial — %s",
                run_id, warning,
            )


def run_import_hubspot_contacts(run_id: int, self_task=None) -> None:
    """Paginate and UPSERT all HubSpot contacts into hubspot_contacts, then
    backfill deal associations via the v4 batch API.

    The CRM v3 list endpoint silently returns an empty ``associations`` block
    for all contacts, so we run a separate v4 batch read after the import to
    populate ``raw_payload["associations"]["deals"]`` for every contact.

    Requirements: 7.6, 7.7, 7.8, 8.2, 8.6, 20.2, 20.3
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()

    # Step 1 — standard paginated import (stores contacts without associations)
    _run_import_generic(
        run_id=run_id,
        object_type='contacts',
        model_class_name='HubSpotContact',
        fetch_method_name='fetch_all_contacts',
        self_task=self_task,
    )

    # Step 2 — backfill deal associations via v4 batch API
    with app.app_context():
        from app import db
        from app.models import HubSpotConfig, HubSpotImportRun
        from app.services.hubspot_client_service import HubSpotClientService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            logger.warning(
                "run_import_hubspot_contacts: skipping association backfill — no HubSpotConfig"
            )
            return

        try:
            _backfill_contact_deal_associations(app, db, HubSpotClientService(config))
            _check_association_health(db, 'contacts', run_id)
        except Exception as exc:
            logger.error(
                "run_import_hubspot_contacts: association backfill failed for run_id=%d: %s",
                run_id, exc, exc_info=True,
            )
            run = HubSpotImportRun.query.get(run_id)
            if run:
                run.status = 'partial'
                run.error_message = f"Association backfill failed: {exc}"
                db.session.commit()
            raise


def _backfill_contact_deal_associations(app, db, client) -> None:
    """Fetch deal associations for all contacts via the v4 batch API and
    merge them into each contact's ``raw_payload["associations"]["deals"]``.

    Mirror of :func:`_backfill_deal_contact_associations` for the contact→deal
    direction.  Safe to call multiple times — existing deal IDs in the payload
    are preserved; new ones from HubSpot are merged in.
    """
    from app.models import HubSpotContact

    all_contacts = HubSpotContact.query.all()
    contact_ids = [c.hubspot_id for c in all_contacts]
    id_to_contact = {c.hubspot_id: c for c in all_contacts}

    if not contact_ids:
        logger.info("_backfill_contact_deal_associations: no contacts to process")
        return

    logger.info(
        "_backfill_contact_deal_associations: fetching associations for %d contacts",
        len(contact_ids),
    )

    try:
        assoc_map = client.fetch_contact_deal_associations(contact_ids)
    except Exception as exc:
        logger.error(
            "_backfill_contact_deal_associations: failed to fetch associations: %s", exc
        )
        raise

    updated = 0
    for contact_id, deal_ids in assoc_map.items():
        contact = id_to_contact.get(contact_id)
        if contact is None:
            continue
        if not deal_ids:
            continue

        payload = dict(contact.raw_payload or {})
        assoc = dict(payload.get("associations", {}))
        deals_block = dict(assoc.get("deals", {}))
        existing_results = list(deals_block.get("results", []))
        existing_ids = {str(r.get("id", "")) for r in existing_results}

        new_results = list(existing_results)
        for did in deal_ids:
            if did not in existing_ids:
                new_results.append({"id": did, "type": "contact_to_deal"})
                existing_ids.add(did)

        if len(new_results) == len(existing_results):
            continue

        deals_block["results"] = new_results
        assoc["deals"] = deals_block
        payload["associations"] = assoc
        contact.raw_payload = payload
        db.session.add(contact)
        updated += 1

        if updated % 100 == 0:
            db.session.commit()
            logger.debug(
                "_backfill_contact_deal_associations: committed %d updates so far", updated
            )

    db.session.commit()
    logger.info(
        "_backfill_contact_deal_associations: complete — %d contacts updated with deal associations",
        updated,
    )


# ---------------------------------------------------------------------------
# Task 3: import_hubspot_companies
# ---------------------------------------------------------------------------

def run_import_hubspot_companies(run_id: int, self_task=None) -> None:
    """Paginate and UPSERT all HubSpot companies into hubspot_companies.

    Requirements: 7.6, 7.7, 7.8, 8.3, 8.6, 20.2, 20.3
    """
    _run_import_generic(
        run_id=run_id,
        object_type='companies',
        model_class_name='HubSpotCompany',
        fetch_method_name='fetch_all_companies',
        self_task=self_task,
    )


# ---------------------------------------------------------------------------
# Task 4: import_hubspot_engagements
# ---------------------------------------------------------------------------

def run_import_hubspot_engagements(run_id: int, self_task=None) -> None:
    """Paginate and UPSERT all HubSpot engagements into hubspot_engagements.

    Engagements have an extra ``engagement_type`` column extracted from the
    payload's ``engagement.type`` field (NOTE, CALL, TASK).

    The legacy engagements API returns records with the ID nested at
    ``record['engagement']['id']`` rather than at the top-level ``id`` field
    used by CRM v3 objects.

    Requirements: 7.6, 7.7, 7.8, 8.4, 8.6, 20.2, 20.3
    """
    def _extract_engagement_type(record: dict) -> dict:
        engagement_type = (
            record.get('engagement', {}).get('type')
            or record.get('type')
            or 'UNKNOWN'
        )
        return {'engagement_type': str(engagement_type).upper()}

    def _extract_engagement_id(record: dict) -> str:
        """Extract the HubSpot engagement ID from the nested engagement object."""
        return str(
            record.get('engagement', {}).get('id')
            or record.get('id')
            or ''
        )

    _run_import_generic(
        run_id=run_id,
        object_type='engagements',
        model_class_name='HubSpotEngagement',
        fetch_method_name='fetch_all_engagements',
        self_task=self_task,
        extra_value_extractor=_extract_engagement_type,
        id_extractor=_extract_engagement_id,
    )


# ---------------------------------------------------------------------------
# Task 5: run_hubspot_matching
# ---------------------------------------------------------------------------

def run_hubspot_matching(run_id: int = None) -> None:
    """Process all unmatched HubSpot records via HubSpotMatcherService.

    Iterates over HubSpotDeal, HubSpotContact, and HubSpotCompany records
    that do not yet have a HubSpotMatch record, and calls the matcher
    service to produce match records.

    Requirements: 9.4
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import HubSpotDeal, HubSpotContact, HubSpotCompany, HubSpotMatch, Lead
        from app.services.hubspot_matcher_service import HubSpotMatcherService

        matcher = HubSpotMatcherService()

        # --- Heal dangling confirmed matches (Bug 4) -----------------------
        # ``internal_record_id`` is a plain Integer with no FK/cascade, so
        # deleting a Lead silently orphans any HubSpotMatch that pointed at it.
        # Such a match stays status='confirmed' referencing a now-missing lead,
        # which means: (a) the skip-set below excludes it from re-matching, and
        # (b) run_enrich_leads_from_hubspot's ``Lead.query.get`` returns None and
        # bails — so a surviving duplicate lead (same address) is never linked to
        # the deal/owner/activities. This happened with 2553 N Drake / Gilberto
        # Olivares after the originally-matched lead was deleted.
        #
        # Reset every confirmed lead-match whose referenced lead no longer
        # exists back to 'pending'/internal_record_id=NULL. Because this runs
        # BEFORE the skip-sets are built, the healed rows fall through to the
        # normal match_deal/match_contact calls below and get re-pointed to the
        # surviving lead in this same run. Only matches whose lead is actually
        # missing are touched — confirmed matches with a live lead, and all
        # rejected matches, are left exactly as-is.
        dangling_candidates = (
            HubSpotMatch.query
            .filter_by(status='confirmed', internal_record_type='lead')
            .filter(HubSpotMatch.internal_record_id.isnot(None))
            .all()
        )
        healed = 0
        referenced_lead_ids = {m.internal_record_id for m in dangling_candidates}
        if referenced_lead_ids:
            # Single batched existence check — never N per-row queries.
            existing_lead_ids = {
                row[0]
                for row in db.session.query(Lead.id)
                .filter(Lead.id.in_(referenced_lead_ids))
                .all()
            }
            for m in dangling_candidates:
                if m.internal_record_id not in existing_lead_ids:
                    m.status = 'pending'
                    m.internal_record_id = None
                    healed += 1
            if healed:
                db.session.commit()
        logger.info(
            "run_hubspot_matching: healed %d dangling confirmed matches "
            "(referenced lead deleted)",
            healed,
        )

        # Collect hubspot_ids that already have a CONFIRMED or REJECTED match record.
        # CONFIRMED = already processed and accepted; REJECTED = reviewer decided no match.
        # Both are skipped so _upsert_match() cannot overwrite a reviewer's decision.
        # UNMATCHED and PENDING records are re-evaluated on each run:
        # - UNMATCHED: may now have address data after a re-import
        # - PENDING: single-match address deals are now auto-confirmed, so
        #   re-running match_deal will upgrade them to confirmed
        matched_deals = {
            m.hubspot_id
            for m in HubSpotMatch.query.filter_by(hubspot_record_type='deal')
            .filter(HubSpotMatch.status.in_(['confirmed', 'rejected']))
            .all()
        }
        matched_contacts = {
            m.hubspot_id
            for m in HubSpotMatch.query.filter_by(hubspot_record_type='contact')
            .filter(HubSpotMatch.status.in_(['confirmed', 'rejected']))
            .all()
        }
        matched_companies = {
            m.hubspot_id
            for m in HubSpotMatch.query.filter_by(hubspot_record_type='company')
            .filter(HubSpotMatch.status.in_(['confirmed', 'rejected']))
            .all()
        }

        deal_errors = 0
        # Fetch stage label map once for the whole loop — avoids N API calls
        _stage_label_map: dict = {}
        try:
            from app.models.hubspot_config import HubSpotConfig as _HubSpotConfig
            from app.services.hubspot_client_service import HubSpotClientService as _HCS
            _config = _HubSpotConfig.query.order_by(_HubSpotConfig.id.desc()).first()
            if _config:
                _stage_label_map = _HCS(_config).fetch_pipeline_stage_labels("deals")
        except Exception as _exc:
            logger.debug("run_hubspot_matching: could not fetch stage labels: %s", _exc)

        for deal in HubSpotDeal.query.all():
            if deal.hubspot_id in matched_deals:
                continue
            try:
                matcher.match_deal(deal, stage_label_map=_stage_label_map)
                db.session.commit()
            except Exception as exc:
                logger.warning(
                    "run_hubspot_matching: error matching deal hubspot_id=%s: %s",
                    deal.hubspot_id, exc,
                )
                deal_errors += 1
                db.session.rollback()

        contact_errors = 0
        for contact in HubSpotContact.query.all():
            if contact.hubspot_id in matched_contacts:
                continue
            try:
                matcher.match_contact(contact)
                db.session.commit()
            except Exception as exc:
                logger.warning(
                    "run_hubspot_matching: error matching contact hubspot_id=%s: %s",
                    contact.hubspot_id, exc,
                )
                contact_errors += 1
                db.session.rollback()

        company_errors = 0
        for company in HubSpotCompany.query.all():
            if company.hubspot_id in matched_companies:
                continue
            try:
                matcher.match_company(company)
                db.session.commit()
            except Exception as exc:
                logger.warning(
                    "run_hubspot_matching: error matching company hubspot_id=%s: %s",
                    company.hubspot_id, exc,
                )
                company_errors += 1
                db.session.rollback()

        logger.info(
            "run_hubspot_matching: complete — deal_errors=%d contact_errors=%d company_errors=%d",
            deal_errors, contact_errors, company_errors,
        )


# ---------------------------------------------------------------------------
# Task 5b: enrich_leads_from_hubspot  (backfill + ongoing sync)
# ---------------------------------------------------------------------------

def run_enrich_leads_from_hubspot(run_id: int = None) -> dict:
    """Enrich leads from all confirmed HubSpot deal and contact matches.

    This is a source-agnostic enrichment pass: for every lead that has a
    confirmed deal or contact match (regardless of how the lead was originally
    imported — Driving for Dollars, Google Sheets, DuPage GIS, etc.), each
    confirmed deal is **re-fetched live from HubSpot** before enriching the lead.
    missing fields onto the lead.

    Safe to run repeatedly — existing non-null lead fields are never overwritten
    (except ``hubspot_deal_stage``, which is always synced as a CRM signal).

    Returns a summary dict with counts.

    Requirements: multi-source lead enrichment
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import Lead, HubSpotDeal, HubSpotContact, HubSpotMatch
        from app.services.hubspot_matcher_service import HubSpotMatcherService
        from app.services.action_engine_service import ActionEngineService

        matcher = HubSpotMatcherService()

        # Fetch portal stage label map once — used to translate stage IDs to
        # display labels (e.g. 'closedlost' → 'Negotiating Remote')
        stage_label_map = {}
        _client = None
        _sync = None
        _contact_sync = None
        try:
            from app.models.hubspot_config import HubSpotConfig
            from app.services.hubspot_client_service import HubSpotClientService
            from app.services.hubspot_deal_sync_service import HubSpotDealSyncService
            from app.services.hubspot_contact_sync_service import HubSpotContactSyncService
            _config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            if _config:
                _client = HubSpotClientService(_config)
                _sync = HubSpotDealSyncService(_client)
                _contact_sync = HubSpotContactSyncService(_client)
                stage_label_map = _client.fetch_pipeline_stage_labels("deals")
                logger.info(
                    "run_enrich_leads_from_hubspot: loaded %d stage labels",
                    len(stage_label_map),
                )
        except Exception as exc:
            logger.warning(
                "run_enrich_leads_from_hubspot: could not fetch stage labels: %s", exc
            )

        deal_enriched = 0
        deal_errors = 0
        deal_refreshed = 0
        contact_enriched = 0
        contact_errors = 0
        contact_refreshed = 0
        action_recomputed = 0

        # --- Enrich from confirmed deal matches ----------------------------
        confirmed_deal_matches = (
            HubSpotMatch.query
            .filter_by(hubspot_record_type='deal', status='confirmed',
                       internal_record_type='lead')
            .filter(HubSpotMatch.internal_record_id.isnot(None))
            .all()
        )
        for match in confirmed_deal_matches:
            try:
                lead = Lead.query.get(match.internal_record_id)
                if lead is None:
                    continue
                deal = None
                if _sync is not None:
                    deal = _sync.refresh_deal_from_api(match.hubspot_id)
                    if deal:
                        deal_refreshed += 1
                else:
                    deal = HubSpotDeal.query.filter_by(
                        hubspot_id=match.hubspot_id
                    ).first()
                if deal is None:
                    continue
                enriched = matcher.enrich_lead_from_deal(lead, deal, stage_label_map)
                if enriched:
                    db.session.commit()
                    deal_enriched += 1
                    logger.debug(
                        "run_enrich_leads_from_hubspot: lead_id=%d deal enriched fields=%s",
                        lead.id, enriched,
                    )
            except Exception as exc:
                logger.warning(
                    "run_enrich_leads_from_hubspot: deal match lead_id=%s error: %s",
                    match.internal_record_id, exc,
                )
                deal_errors += 1
                db.session.rollback()

        # --- Enrich from confirmed contact matches -------------------------
        confirmed_contact_matches = (
            HubSpotMatch.query
            .filter_by(hubspot_record_type='contact', status='confirmed',
                       internal_record_type='lead')
            .filter(HubSpotMatch.internal_record_id.isnot(None))
            .all()
        )
        for match in confirmed_contact_matches:
            try:
                lead = Lead.query.get(match.internal_record_id)
                contact = None
                if _contact_sync is not None:
                    contact = _contact_sync.refresh_contact_from_api(match.hubspot_id)
                    if contact:
                        contact_refreshed += 1
                else:
                    contact = HubSpotContact.query.filter_by(
                        hubspot_id=match.hubspot_id
                    ).first()
                if lead is None or contact is None:
                    continue
                enriched = matcher.enrich_lead_from_contact(lead, contact)
                if enriched:
                    db.session.commit()
                    contact_enriched += 1
                    logger.debug(
                        "run_enrich_leads_from_hubspot: lead_id=%d contact enriched fields=%s",
                        lead.id, enriched,
                    )
            except Exception as exc:
                logger.warning(
                    "run_enrich_leads_from_hubspot: contact match lead_id=%s error: %s",
                    match.internal_record_id, exc,
                )
                contact_errors += 1
                db.session.rollback()

        # --- Also match contacts via deal associations ----------------------
        # For each confirmed deal match, check if the HubSpot deal has
        # associated contact IDs in its raw payload and try to enrich the
        # lead from those contacts.  Also updates the HubSpotMatch record for
        # each associated contact so its internal_record_id points to the
        # property instead of being NULL.
        for match in confirmed_deal_matches:
            try:
                lead = Lead.query.get(match.internal_record_id)
                deal = HubSpotDeal.query.filter_by(
                    hubspot_id=match.hubspot_id
                ).first()
                if lead is None or deal is None:
                    continue
                # HubSpot deal payload may carry associations.contacts list
                assoc = (deal.raw_payload or {}).get("associations", {})
                contact_ids = (
                    assoc.get("contacts", {}).get("results", [])
                    if isinstance(assoc.get("contacts"), dict)
                    else []
                )
                if not contact_ids:
                    logger.warning(
                        "run_enrich_leads_from_hubspot: deal %s has empty contacts block — "
                        "retrying v4 associations fetch", deal.hubspot_id,
                    )
                    if _client:
                        # Bounded retry/backoff: a transient v4 failure (rate
                        # limit / 5xx / timeout) is retried before giving up,
                        # rather than a single best-effort attempt.
                        raw_ids = _fetch_deal_contact_associations_with_retry(
                            _client, deal.hubspot_id
                        )
                        contact_ids = [{"id": cid} for cid in raw_ids]
                for assoc_entry in contact_ids:
                    cid = str(assoc_entry.get("id", ""))
                    if not cid:
                        continue
                    assoc_contact = None
                    if _contact_sync is not None:
                        assoc_contact = _contact_sync.refresh_contact_from_api(cid)
                        if assoc_contact:
                            contact_refreshed += 1
                    else:
                        assoc_contact = HubSpotContact.query.filter_by(
                            hubspot_id=cid
                        ).first()
                    if assoc_contact is None:
                        continue
                    enriched = matcher.enrich_lead_from_contact(lead, assoc_contact)
                    if enriched:
                        db.session.commit()
                        contact_enriched += 1
                        logger.debug(
                            "run_enrich_leads_from_hubspot: lead_id=%d associated contact %s enriched fields=%s",
                            lead.id, cid, enriched,
                        )
                    # Update the HubSpotMatch for this contact so its
                    # internal_record_id points to the property.  This fixes
                    # the case where match_contact() ran before the deal was
                    # matched and left internal_record_id = NULL.
                    # Only update still-pending rows — never flip rejected matches.
                    contact_match = HubSpotMatch.query.filter_by(
                        hubspot_record_type='contact',
                        hubspot_id=cid,
                        status='pending',
                    ).filter(HubSpotMatch.internal_record_id.is_(None)).first()
                    if contact_match:
                        contact_match.internal_record_type = 'lead'
                        contact_match.internal_record_id = lead.id
                        contact_match.status = 'confirmed'
                        db.session.commit()
                        logger.debug(
                            "run_enrich_leads_from_hubspot: updated contact match %s -> lead_id=%d",
                            cid, lead.id,
                        )
            except Exception as exc:
                logger.warning(
                    "run_enrich_leads_from_hubspot: deal assoc enrich lead_id=%s error: %s",
                    match.internal_record_id, exc,
                )
                db.session.rollback()

        # --- Also resolve contacts whose match has internal_record_id=NULL --
        # When contacts were imported before their associated deals were
        # matched, their HubSpotMatch ends up with internal_record_id=NULL.
        # Now that deals are confirmed, use each contact's deal associations
        # (fetched during import via associations=deals) to find the property.
        unresolved_contact_matches = (
            HubSpotMatch.query
            .filter_by(hubspot_record_type='contact')
            .filter(HubSpotMatch.status.in_(['confirmed', 'pending']))
            .filter(HubSpotMatch.internal_record_id.is_(None))
            .all()
        )
        for contact_match in unresolved_contact_matches:
            try:
                hs_contact = HubSpotContact.query.filter_by(
                    hubspot_id=contact_match.hubspot_id
                ).first()
                if hs_contact is None:
                    continue
                # Look for deal associations in the contact's raw payload
                assoc = (hs_contact.raw_payload or {}).get("associations", {})
                deal_results = (
                    assoc.get("deals", {}).get("results", [])
                    if isinstance(assoc.get("deals"), dict)
                    else []
                )
                for deal_entry in deal_results:
                    did = str(deal_entry.get("id", ""))
                    if not did:
                        continue
                    # Find the confirmed deal match for this deal ID
                    deal_match = HubSpotMatch.query.filter_by(
                        hubspot_record_type='deal',
                        hubspot_id=did,
                        status='confirmed',
                    ).filter(HubSpotMatch.internal_record_id.isnot(None)).first()
                    if deal_match is None:
                        continue
                    lead = Lead.query.get(deal_match.internal_record_id)
                    if lead is None:
                        continue
                    # Enrich the lead and link the contact
                    enriched = matcher.enrich_lead_from_contact(lead, hs_contact)
                    if enriched:
                        db.session.commit()
                        contact_enriched += 1
                    # Update the contact's match record. Promote it to
                    # 'confirmed' (not just back-filling internal_record_id) so
                    # the downstream _resolve_associations() — which only links
                    # engagements for confirmed matches — includes this contact.
                    # A resolved-but-still-pending match would otherwise be
                    # skipped, leaving its activities orphaned.
                    contact_match.internal_record_type = 'lead'
                    contact_match.internal_record_id = lead.id
                    contact_match.status = 'confirmed'
                    db.session.commit()
                    logger.debug(
                        "run_enrich_leads_from_hubspot: resolved unlinked contact %s -> lead_id=%d via deal %s",
                        contact_match.hubspot_id, lead.id, did,
                    )
                    break  # one deal association is enough to anchor the contact
            except Exception as exc:
                logger.warning(
                    "run_enrich_leads_from_hubspot: unresolved contact %s error: %s",
                    contact_match.hubspot_id, exc,
                )
                db.session.rollback()

        # --- Recompute recommended_action for all touched leads ------------
        touched_lead_ids = {
            m.internal_record_id
            for m in confirmed_deal_matches + confirmed_contact_matches
            if m.internal_record_id
        }
        for lead_id in touched_lead_ids:
            try:
                ActionEngineService.recompute_and_persist(lead_id)
                action_recomputed += 1
            except Exception as exc:
                logger.warning(
                    "run_enrich_leads_from_hubspot: recompute failed for lead_id=%d: %s",
                    lead_id, exc,
                )
                db.session.rollback()

        summary = {
            'deal_refreshed': deal_refreshed,
            'deal_enriched': deal_enriched,
            'deal_errors': deal_errors,
            'contact_enriched': contact_enriched,
            'contact_errors': contact_errors,
            'action_recomputed': action_recomputed,
        }
        logger.info("run_enrich_leads_from_hubspot: complete — %s", summary)
        return summary


# ---------------------------------------------------------------------------
# Task 5b: sync_hubspot_tasks_for_confirmed_leads
# ---------------------------------------------------------------------------

def run_sync_hubspot_tasks_for_confirmed_leads(limit: int = 200) -> dict:
    """Live-sync HubSpot CRM tasks for all leads with confirmed deal matches."""
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.services.hubspot_deal_sync_service import HubSpotDealSyncService
        return HubSpotDealSyncService().sync_all_confirmed_lead_tasks(limit=limit)


# ---------------------------------------------------------------------------
# Task 5c: refresh_confirmed_hubspot_deals
# ---------------------------------------------------------------------------

def run_refresh_confirmed_hubspot_deals(limit: int = 200) -> dict:
    """Re-fetch confirmed deals from HubSpot API and enrich linked leads."""
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.services.hubspot_deal_sync_service import HubSpotDealSyncService
        return HubSpotDealSyncService().refresh_all_confirmed_deals(limit=limit)


# ---------------------------------------------------------------------------
# Task 6: convert_hubspot_activities
# ---------------------------------------------------------------------------

def run_convert_hubspot_activities(run_id: int = None) -> None:
    """Convert all unconverted HubSpotEngagement records to Interactions/Tasks.

    Skips any engagement whose hubspot_id already exists as a
    ``hubspot_engagement_id`` in the interactions table or as a
    ``hubspot_task_id`` in the tasks table (idempotent).

    Requirements: 9.4
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import HubSpotEngagement, Interaction, Task
        from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService

        converter = HubSpotActivityConverterService()

        # Build sets of already-converted engagement IDs for fast O(1) lookup
        existing_interaction_ids = {
            row[0]
            for row in db.session.query(Interaction.hubspot_engagement_id)
            .filter(Interaction.hubspot_engagement_id.isnot(None))
            .all()
        }
        existing_task_ids = {
            row[0]
            for row in db.session.query(Task.hubspot_task_id)
            .filter(Task.hubspot_task_id.isnot(None))
            .all()
        }

        converted = 0
        skipped = 0
        errors = 0

        for engagement in HubSpotEngagement.query.all():
            eid = engagement.hubspot_id

            # Reconcile existing HubSpot tasks from updated engagement payloads
            if eid in existing_task_ids:
                if (engagement.engagement_type or '').upper() == 'TASK':
                    try:
                        if converter.reconcile_task_from_engagement(engagement):
                            converted += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        logger.warning(
                            "run_convert_hubspot_activities: reconcile error hubspot_id=%s: %s",
                            eid, exc,
                        )
                        errors += 1
                        db.session.rollback()
                else:
                    skipped += 1
                continue

            # Skip if already converted to an Interaction
            if eid in existing_interaction_ids:
                skipped += 1
                continue

            try:
                result = converter.convert_engagement(engagement)
                if result is not None:
                    db.session.add(result)
                    db.session.commit()
                    converted += 1
                else:
                    # Unrecognized engagement type — skip silently
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "run_convert_hubspot_activities: error converting engagement hubspot_id=%s: %s",
                    eid, exc,
                )
                errors += 1
                db.session.rollback()

        logger.info(
            "run_convert_hubspot_activities: complete — converted=%d skipped=%d errors=%d",
            converted, skipped, errors,
        )

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

        # --- Re-point associations stranded on a deleted lead (Bug 5) ------
        # InteractionAssociation.target_id and TaskAssociation.target_id are
        # plain Integers with no FK/cascade to ``leads``, so deleting a
        # duplicate lead silently leaves any hubspot-imported activity/task
        # association pointing at the now-missing lead — with
        # Interaction.is_orphaned=False. The orphan pass above only revisits
        # is_orphaned=True rows, and the converter is idempotent, so these
        # historical rows stay stranded on the dead lead and never surface on
        # the surviving lead. Bug 4 healing has already re-pointed the deal/
        # contact match to the surviving lead, so re-resolving the engagement
        # now yields the correct current lead. (2553 N Drake: lead 916 -> 3415.)
        #
        # Only associations whose target lead is ACTUALLY missing are touched;
        # associations pointing at a live lead are left exactly as-is. Scope is
        # limited to hubspot-imported interactions (source='hubspot_import' with
        # a non-null hubspot_engagement_id) and hubspot-imported tasks (non-null
        # hubspot_task_id) — manually-created records are never touched. The
        # pass is idempotent: once re-pointed, nothing references the dead lead,
        # so a second run is a no-op.
        from app.models import Lead, Task, TaskAssociation

        stranded_interaction_assocs = (
            db.session.query(InteractionAssociation, Interaction)
            .join(Interaction, InteractionAssociation.interaction_id == Interaction.id)
            .filter(
                InteractionAssociation.target_type == 'lead',
                Interaction.source == 'hubspot_import',
                Interaction.hubspot_engagement_id.isnot(None),
            )
            .all()
        )
        stranded_task_assocs = (
            db.session.query(TaskAssociation, Task)
            .join(Task, TaskAssociation.task_id == Task.id)
            .filter(
                TaskAssociation.target_type == 'lead',
                Task.hubspot_task_id.isnot(None),
            )
            .all()
        )

        # Single batched existence check across BOTH passes — never N per-row
        # queries. Collect distinct lead target_ids, run one Lead.id.in_(...)
        # query, and derive the set of ids whose lead no longer exists.
        candidate_lead_ids = (
            {assoc.target_id for assoc, _ in stranded_interaction_assocs}
            | {assoc.target_id for assoc, _ in stranded_task_assocs}
        )

        re_pointed = 0
        re_point_errors = 0
        if candidate_lead_ids:
            existing_lead_ids = {
                row[0]
                for row in db.session.query(Lead.id)
                .filter(Lead.id.in_(candidate_lead_ids))
                .all()
            }
            missing_lead_ids = candidate_lead_ids - existing_lead_ids

            if missing_lead_ids:
                # Dedupe to affected interactions/tasks BEFORE mutating anything
                # (so the second pass's captured ids aren't disturbed by commits).
                affected_interactions = {}
                for assoc, interaction in stranded_interaction_assocs:
                    if assoc.target_id in missing_lead_ids:
                        affected_interactions[interaction.id] = interaction

                affected_tasks = {}
                for assoc, task in stranded_task_assocs:
                    if assoc.target_id in missing_lead_ids:
                        affected_tasks[task.id] = task

                # 1. INTERACTIONS — re-point each affected interaction once.
                for interaction in affected_interactions.values():
                    try:
                        resolved = converter._resolve_associations_by_engagement_id(
                            interaction.hubspot_engagement_id
                        )
                        if resolved:
                            # Replace the dangling lead association(s): delete the
                            # row(s) pointing at a missing lead, then add the
                            # resolved targets (deduped against existing rows).
                            for row in InteractionAssociation.query.filter_by(
                                interaction_id=interaction.id, target_type='lead'
                            ).all():
                                if row.target_id in missing_lead_ids:
                                    db.session.delete(row)
                            db.session.flush()
                            for a in resolved:
                                exists = InteractionAssociation.query.filter_by(
                                    interaction_id=interaction.id,
                                    target_type=a['target_type'],
                                    target_id=a['target_id'],
                                ).first()
                                if exists is None:
                                    db.session.add(InteractionAssociation(
                                        interaction_id=interaction.id,
                                        target_type=a['target_type'],
                                        target_id=a['target_id'],
                                    ))
                            interaction.is_orphaned = False
                            db.session.commit()
                            re_pointed += 1
                            logger.debug(
                                "run_convert_hubspot_activities: re-pointed stranded "
                                "interaction id=%s off deleted lead", interaction.id,
                            )
                        else:
                            # Engagement gone or no confirmed match — keep the data
                            # but flag for the orphan pass to revisit on a later run.
                            interaction.is_orphaned = True
                            db.session.commit()
                    except Exception as exc:
                        logger.warning(
                            "run_convert_hubspot_activities: stranded re-point error "
                            "for interaction id=%s: %s", interaction.id, exc,
                        )
                        re_point_errors += 1
                        db.session.rollback()

                # 2. TASKS — re-point each affected task once. The Task's
                #    hubspot_task_id IS the engagement id. Keep only
                #    ('lead','organization') targets (mirrors convert_task).
                for task in affected_tasks.values():
                    try:
                        resolved = [
                            a for a in converter._resolve_associations_by_engagement_id(
                                task.hubspot_task_id
                            )
                            if a.get('target_type') in ('lead', 'organization')
                        ]
                        if resolved:
                            for row in TaskAssociation.query.filter_by(
                                task_id=task.id, target_type='lead'
                            ).all():
                                if row.target_id in missing_lead_ids:
                                    db.session.delete(row)
                            db.session.flush()
                            for a in resolved:
                                exists = TaskAssociation.query.filter_by(
                                    task_id=task.id,
                                    target_type=a['target_type'],
                                    target_id=a['target_id'],
                                ).first()
                                if exists is None:
                                    db.session.add(TaskAssociation(
                                        task_id=task.id,
                                        target_type=a['target_type'],
                                        target_id=a['target_id'],
                                    ))
                            db.session.commit()
                            re_pointed += 1
                            logger.debug(
                                "run_convert_hubspot_activities: re-pointed stranded "
                                "task id=%s off deleted lead", task.id,
                            )
                    except Exception as exc:
                        logger.warning(
                            "run_convert_hubspot_activities: stranded re-point error "
                            "for task id=%s: %s", task.id, exc,
                        )
                        re_point_errors += 1
                        db.session.rollback()

        logger.info(
            "run_convert_hubspot_activities: stranded-lead re-point — "
            "re_pointed=%d errors=%d",
            re_pointed, re_point_errors,
        )


# ---------------------------------------------------------------------------
# Task 7: extract_hubspot_signals
# ---------------------------------------------------------------------------

def run_extract_hubspot_signals(run_id: int = None) -> None:
    """Extract signals from all HubSpot-imported Interactions and apply suppression flags.

    Iterates over all Interaction records with source='hubspot_import', runs
    the signal extractor, persists new HubSpotSignal records, and applies
    suppression flags to associated Lead records.

    Requirements: 9.4
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import Interaction, InteractionAssociation
        from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

        extractor = HubSpotSignalExtractorService()

        processed = 0
        signal_count = 0
        errors = 0

        # Query all HubSpot-imported interactions
        interactions = (
            Interaction.query
            .filter_by(source='hubspot_import')
            .all()
        )

        for interaction in interactions:
            try:
                # Resolve lead_id from InteractionAssociation (target_type='lead')
                lead_assoc = (
                    InteractionAssociation.query
                    .filter_by(interaction_id=interaction.id, target_type='lead')
                    .first()
                )
                if lead_assoc is None:
                    # No lead association — skip signal extraction for this interaction
                    continue

                lead_id = lead_assoc.target_id

                # Extract signals — pass the interaction directly.
                # The extractor's _get_body_text reads raw_payload for HubSpotEngagement
                # objects, but Interaction objects have a plain .body field.
                # We create a lightweight adapter so the extractor works with both.
                class _InteractionAdapter:
                    """Adapter so HubSpotSignalExtractorService can read Interaction.body."""
                    def __init__(self, interaction):
                        # Wrap body in the raw_payload structure the extractor expects
                        self.raw_payload = {'metadata': {'body': interaction.body or ''}}
                        self.hubspot_id = interaction.hubspot_engagement_id

                signals = extractor.extract_signals(_InteractionAdapter(interaction), lead_id)

                for signal in signals:
                    db.session.add(signal)
                    signal_count += 1

                # Apply suppression flags for DO_NOT_CONTACT / WRONG_NUMBER signals
                if signals:
                    extractor.apply_suppression(signals)

                db.session.commit()

                # Set is_warm flag on the lead if any warm signal was detected (Req 4.3, 9.1-9.3)
                try:
                    warm_signals = [s for s in signals if s.signal_type in WARM_SIGNAL_TYPES]
                    if warm_signals:
                        from app.models import Lead as _Lead
                        lead_obj = db.session.get(_Lead, lead_id)
                        if lead_obj is not None and not lead_obj.is_warm:
                            lead_obj.is_warm = True
                            db.session.add(lead_obj)
                            db.session.commit()
                except Exception as warm_exc:
                    logger.warning(
                        "run_extract_hubspot_signals: failed to set is_warm for lead_id=%s: %s",
                        lead_id, warm_exc,
                    )
                    db.session.rollback()

                processed += 1

            except Exception as exc:
                logger.warning(
                    "run_extract_hubspot_signals: error processing interaction id=%d: %s",
                    interaction.id, exc,
                )
                errors += 1
                db.session.rollback()

        logger.info(
            "run_extract_hubspot_signals: complete — processed=%d signals=%d errors=%d",
            processed, signal_count, errors,
        )


# ---------------------------------------------------------------------------
# Task 8: rescore_leads_after_import
# ---------------------------------------------------------------------------

def run_rescore_leads_after_import(user_id: str = 'default') -> int:
    """Trigger LeadScoringEngine.bulk_rescore() after HubSpot signal extraction.

    Passes HubSpot signals to compute_score for each lead so that signal
    adjustments are reflected in the final lead scores.

    Requirements: 9.4
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.services import LeadScoringEngine

        engine = LeadScoringEngine()
        rescored = engine.bulk_rescore(user_id)

        logger.info(
            "run_rescore_leads_after_import: user_id=%s rescored=%d leads",
            user_id, rescored,
        )
        return rescored


# ---------------------------------------------------------------------------
# Task 9: generate_backup_export
# ---------------------------------------------------------------------------

def run_generate_backup_export() -> str:
    """Serialize all raw HubSpot tables to JSON and write to a temp file.

    Produces a JSON file at /tmp/hubspot_backup_{timestamp}.json containing:
      - metadata: export timestamp, record counts per table
      - deals: list of all HubSpotDeal records
      - contacts: list of all HubSpotContact records
      - companies: list of all HubSpotCompany records
      - engagements: list of all HubSpotEngagement records
      - import_runs: list of all HubSpotImportRun records

    Returns the path to the generated file.

    Requirements: 9.4
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app.models import (
            HubSpotDeal,
            HubSpotContact,
            HubSpotCompany,
            HubSpotEngagement,
            HubSpotImportRun,
        )

        def _serialize_deal(d) -> dict:
            return {
                'id': d.id,
                'hubspot_id': d.hubspot_id,
                'raw_payload': d.raw_payload,
                'import_run_id': d.import_run_id,
                'first_imported_at': d.first_imported_at.isoformat() if d.first_imported_at else None,
                'last_updated_at': d.last_updated_at.isoformat() if d.last_updated_at else None,
            }

        def _serialize_contact(c) -> dict:
            return {
                'id': c.id,
                'hubspot_id': c.hubspot_id,
                'raw_payload': c.raw_payload,
                'import_run_id': c.import_run_id,
                'first_imported_at': c.first_imported_at.isoformat() if c.first_imported_at else None,
                'last_updated_at': c.last_updated_at.isoformat() if c.last_updated_at else None,
            }

        def _serialize_company(co) -> dict:
            return {
                'id': co.id,
                'hubspot_id': co.hubspot_id,
                'raw_payload': co.raw_payload,
                'import_run_id': co.import_run_id,
                'first_imported_at': co.first_imported_at.isoformat() if co.first_imported_at else None,
                'last_updated_at': co.last_updated_at.isoformat() if co.last_updated_at else None,
            }

        def _serialize_engagement(e) -> dict:
            return {
                'id': e.id,
                'hubspot_id': e.hubspot_id,
                'engagement_type': e.engagement_type,
                'raw_payload': e.raw_payload,
                'import_run_id': e.import_run_id,
                'first_imported_at': e.first_imported_at.isoformat() if e.first_imported_at else None,
                'last_updated_at': e.last_updated_at.isoformat() if e.last_updated_at else None,
            }

        def _serialize_run(r) -> dict:
            return {
                'id': r.id,
                'object_type': r.object_type,
                'status': r.status,
                'start_time': r.start_time.isoformat() if r.start_time else None,
                'end_time': r.end_time.isoformat() if r.end_time else None,
                'total_fetched': r.total_fetched,
                'created_count': r.created_count,
                'updated_count': r.updated_count,
                'skipped_count': r.skipped_count,
                'error_count': r.error_count,
                'error_message': r.error_message,
            }

        deals = HubSpotDeal.query.all()
        contacts = HubSpotContact.query.all()
        companies = HubSpotCompany.query.all()
        engagements = HubSpotEngagement.query.all()
        import_runs = HubSpotImportRun.query.order_by(HubSpotImportRun.id).all()

        export_timestamp = datetime.utcnow().isoformat()

        payload = {
            'metadata': {
                'exported_at': export_timestamp,
                'deal_count': len(deals),
                'contact_count': len(contacts),
                'company_count': len(companies),
                'engagement_count': len(engagements),
                'import_run_count': len(import_runs),
            },
            'deals': [_serialize_deal(d) for d in deals],
            'contacts': [_serialize_contact(c) for c in contacts],
            'companies': [_serialize_company(co) for co in companies],
            'engagements': [_serialize_engagement(e) for e in engagements],
            'import_runs': [_serialize_run(r) for r in import_runs],
        }

        # Write to a deterministic temp path so the controller can locate it
        timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        output_path = f'/tmp/hubspot_backup_{timestamp_str}.json'

        try:
            with open(output_path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2, default=str)
        except OSError:
            # Fall back to a system-assigned temp file if /tmp is not writable
            import os
            fd, output_path = tempfile.mkstemp(
                prefix='hubspot_backup_', suffix='.json'
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2, default=str)

        logger.info(
            "run_generate_backup_export: wrote %d deals, %d contacts, %d companies, "
            "%d engagements to %s",
            len(deals), len(contacts), len(companies), len(engagements), output_path,
        )
        return output_path


# ---------------------------------------------------------------------------
# Task 10: nightly_association_sync
# ---------------------------------------------------------------------------

def run_nightly_association_sync() -> dict:
    """Re-fetch deal↔contact associations for all records via the v4 batch API.

    Intended to run nightly via Celery Beat as a catch-all for any associations
    that were missed by the import backfill or webhook handler.  Significantly
    faster than a full import — only the v4 associations endpoint is called,
    not the full CRM list endpoints.

    Returns a summary dict with counts.
    """
    from dotenv import load_dotenv
    load_dotenv()
    from app import create_app

    app = create_app()
    with app.app_context():
        from app import db
        from app.models import HubSpotConfig
        from app.services.hubspot_client_service import HubSpotClientService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            logger.warning("run_nightly_association_sync: no HubSpotConfig — skipping")
            return {"skipped": True, "reason": "no_config"}

        client = HubSpotClientService(config)

        # Re-sync deal → contact associations
        _backfill_deal_contact_associations(app, db, client)

        # Re-sync contact → deal associations
        _backfill_contact_deal_associations(app, db, client)

        logger.info("run_nightly_association_sync: complete")
        return {"status": "complete"}
