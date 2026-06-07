"""Backfill lead enrichment from HubSpot deal and contact matches.

Revision ID: r9s0t1u2v3w4
Revises: z5a6b7c8d9e0
Create Date: 2026-06-07 00:00:00.000000

Changes:
  - Data-only migration: no schema changes.
  - For every confirmed HubSpot deal match, syncs properties.dealstage onto
    leads.hubspot_deal_stage.
  - For every confirmed HubSpot contact match (and deal-associated contacts),
    fills in phone_1–phone_7 / email_1–email_5 flat columns where currently
    null, and updates has_phone / has_email flags.
  - Recomputes recommended_action for all touched leads so that leads whose
    contact data was populated no longer show 'add_contact_info'.

This is idempotent: existing non-null lead fields are preserved.
hubspot_deal_stage is always overwritten with the live stage value.

This migration fixes:
  1. Leads matched to a HubSpot deal showing stale / wrong stage
  2. Leads matched to a HubSpot contact still showing 'add_contact_info'
     because contact phone/email was never synced to the lead flat columns

Source-agnostic: applies to leads from any import source (Driving for Dollars,
Google Sheets, DuPage GIS, etc.) as long as they have a confirmed HubSpot match.
"""
import logging

from alembic import op

logger = logging.getLogger('alembic.runtime.migration')

revision = 'r9s0t1u2v3w4'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    """Run the HubSpot lead enrichment backfill."""
    # We call the enrichment service directly using the current Alembic
    # connection context rather than creating a new Flask app.  The task
    # function (run_enrich_leads_from_hubspot) calls create_app() internally
    # for standalone use, but that causes infinite recursion when called from
    # inside a migration (which is already running inside create_app).
    #
    # Instead, we use the SQLAlchemy session that's already active.
    try:
        from app import db
        from app.models import Lead, HubSpotDeal, HubSpotContact, HubSpotMatch
        from app.services.hubspot_matcher_service import HubSpotMatcherService
        from app.services.action_engine_service import ActionEngineService

        matcher = HubSpotMatcherService()

        # Fetch portal stage label map so IDs are translated to display labels
        stage_label_map = {}
        try:
            from app.models.hubspot_config import HubSpotConfig
            from app.services.hubspot_client_service import HubSpotClientService
            _config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            if _config:
                _client = HubSpotClientService(_config)
                stage_label_map = _client.fetch_pipeline_stage_labels("deals")
                logger.info("Backfill: loaded %d stage labels", len(stage_label_map))
        except Exception as exc:
            logger.warning("Backfill: could not fetch stage labels: %s", exc)

        deal_enriched = 0
        contact_enriched = 0

        # Enrich from confirmed deal matches
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
                deal = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
                if lead and deal:
                    enriched = matcher.enrich_lead_from_deal(lead, deal, stage_label_map)
                    if enriched:
                        db.session.commit()
                        deal_enriched += 1
            except Exception as exc:
                db.session.rollback()
                logger.debug("Backfill: deal enrich lead_id=%s: %s", match.internal_record_id, exc)

        # Enrich from confirmed contact matches
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
                contact = HubSpotContact.query.filter_by(hubspot_id=match.hubspot_id).first()
                if lead and contact:
                    enriched = matcher.enrich_lead_from_contact(lead, contact)
                    if enriched:
                        db.session.commit()
                        contact_enriched += 1
            except Exception as exc:
                db.session.rollback()
                logger.debug("Backfill: contact enrich lead_id=%s: %s", match.internal_record_id, exc)

        # Recompute recommended_action for touched leads
        touched_ids = {m.internal_record_id for m in confirmed_deal_matches + confirmed_contact_matches if m.internal_record_id}
        recomputed = 0
        for lead_id in touched_ids:
            try:
                ActionEngineService.recompute_and_persist(lead_id)
                recomputed += 1
            except Exception:
                db.session.rollback()

        logger.info(
            "Backfill migration r9s0t1u2v3w4 complete: "
            "deal_enriched=%d contact_enriched=%d action_recomputed=%d",
            deal_enriched, contact_enriched, recomputed,
        )
    except Exception as exc:
        logger.warning(
            "Backfill migration r9s0t1u2v3w4: enrichment failed (non-fatal): %s", exc
        )


def downgrade():
    # Data migrations cannot be meaningfully reversed — the enriched fields
    # (phone_1, email_1, hubspot_deal_stage, etc.) were previously null and
    # there is no way to distinguish "was null before migration" from
    # "was null for another reason".  No-op downgrade is intentional.
    pass
