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
    # Import the task function directly — this migration is data-only and
    # relies on the app's service layer rather than raw SQL, because the
    # enrichment logic is intentionally centralised in HubSpotMatcherService
    # to ensure consistency between the migration and the ongoing pipeline.
    #
    # We import inside the function to avoid issues with the Alembic env not
    # having the app configured at module load time.
    try:
        from app.tasks.hubspot_tasks import run_enrich_leads_from_hubspot
        summary = run_enrich_leads_from_hubspot()
        logger.info(
            "Backfill migration a1b2c3d4e5f6 complete: %s", summary
        )
    except Exception as exc:
        # Log but don't fail the migration — the data backfill is best-effort.
        # The same enrichment runs automatically on the next HubSpot import.
        logger.warning(
            "Backfill migration a1b2c3d4e5f6: enrichment failed (non-fatal): %s", exc
        )


def downgrade():
    # Data migrations cannot be meaningfully reversed — the enriched fields
    # (phone_1, email_1, hubspot_deal_stage, etc.) were previously null and
    # there is no way to distinguish "was null before migration" from
    # "was null for another reason".  No-op downgrade is intentional.
    pass
