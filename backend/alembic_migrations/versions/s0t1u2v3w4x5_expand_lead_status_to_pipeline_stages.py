"""Expand lead_status enum to mirror HubSpot pipeline stages.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-06-08 00:00:00.000000

Changes:
  1. Add new enum values to lead_status_enum PostgreSQL type.
  2. Migrate existing data:
     - Leads with a confirmed HubSpot deal match → status from deal's stage label
     - Other leads with phone/email/mailing_address → mailing_no_contact_made
     - Other leads without any contact method → awaiting_skip_trace
     - under_contract → negotiating_remote
     - closed → deal_won
     - nurture → deprioritize
     - new, active, follow_up → apply contact-info rule
  3. Change server_default to 'awaiting_skip_trace'.

New enum values (replacing old set):
  skip_trace, awaiting_skip_trace, mailing_no_contact_made,
  mailing_contacted_no_interest, mailing_contacted_interested,
  negotiating_remote, in_person_appointment, offer_delivered,
  deprioritize, deal_won, deal_lost

Kept: suppressed, do_not_contact
Removed: new, active, follow_up, nurture, under_contract, closed
"""
from alembic import op
import logging

logger = logging.getLogger('alembic.runtime.migration')

revision = 's0t1u2v3w4x5'
down_revision = 'r9s0t1u2v3w4'
branch_labels = None
depends_on = None

# Mapping from HubSpot stage display label → lead_status value
_HS_STAGE_TO_STATUS = {
    'Skip Trace': 'skip_trace',
    'Awaiting Skip Trace': 'awaiting_skip_trace',
    'Mailing, no contact made': 'mailing_no_contact_made',
    'Mailing, contact made, no interest': 'mailing_contacted_no_interest',
    'Mailing, contact made, interested': 'mailing_contacted_interested',
    'Negotiating Remote': 'negotiating_remote',
    'In Person Appointment': 'in_person_appointment',
    'Offer Delivered': 'offer_delivered',
    'Deprioritize': 'deprioritize',
    'Deal Won': 'deal_won',
    'Deal Lost': 'deal_lost',
}


def upgrade():
    # ------------------------------------------------------------------
    # Step 1: Add new enum values to PostgreSQL type.
    # Must be done with ADD VALUE in a SEPARATE transaction from the DML below.
    # PostgreSQL does not allow using newly added enum values in the same
    # transaction as the ALTER TYPE statement.
    # ------------------------------------------------------------------
    new_values = [
        'skip_trace',
        'awaiting_skip_trace',
        'mailing_no_contact_made',
        'mailing_contacted_no_interest',
        'mailing_contacted_interested',
        'negotiating_remote',
        'in_person_appointment',
        'offer_delivered',
        'deprioritize',
        'deal_won',
        'deal_lost',
    ]

    # PostgreSQL ADD VALUE must be committed before being used in DML.
    # We run each ADD VALUE in autocommit mode so it's visible immediately.
    bind = op.get_bind()
    raw_conn = bind.connection
    raw_conn.autocommit = True
    for val in new_values:
        raw_conn.execute(
            f"ALTER TYPE lead_status_enum ADD VALUE IF NOT EXISTS '{val}'"
        )
    raw_conn.autocommit = False

    logger.info("Added new enum values to lead_status_enum")

    # ------------------------------------------------------------------
    # Step 2: Migrate existing data — highest-priority rules first.
    # ------------------------------------------------------------------

    # 2a. Leads with a confirmed HubSpot deal match: derive status from stored stage label
    for stage_label, status_val in _HS_STAGE_TO_STATUS.items():
        op.execute(f"""
            UPDATE leads
            SET lead_status = '{status_val}'
            WHERE lead_status IN ('new', 'active', 'follow_up', 'nurture', 'under_contract', 'closed')
              AND hubspot_deal_stage = '{stage_label}'
        """)

    logger.info("Migrated HubSpot-matched leads to pipeline stage statuses")

    # 2b. under_contract → negotiating_remote (any remaining)
    op.execute("""
        UPDATE leads SET lead_status = 'negotiating_remote'
        WHERE lead_status = 'under_contract'
    """)

    # 2c. closed → deal_won (any remaining)
    op.execute("""
        UPDATE leads SET lead_status = 'deal_won'
        WHERE lead_status = 'closed'
    """)

    # 2d. nurture → deprioritize
    op.execute("""
        UPDATE leads SET lead_status = 'deprioritize'
        WHERE lead_status = 'nurture'
    """)

    # 2e. new / active / follow_up with contact info → mailing_no_contact_made
    op.execute("""
        UPDATE leads
        SET lead_status = 'mailing_no_contact_made'
        WHERE lead_status IN ('new', 'active', 'follow_up')
          AND (
            (phone_1 IS NOT NULL AND phone_1 != '')
            OR (email_1 IS NOT NULL AND email_1 != '')
            OR (mailing_address IS NOT NULL AND mailing_address != '')
            OR has_phone = TRUE
            OR has_email = TRUE
          )
    """)

    # 2f. new / active / follow_up without contact info → awaiting_skip_trace
    op.execute("""
        UPDATE leads
        SET lead_status = 'awaiting_skip_trace'
        WHERE lead_status IN ('new', 'active', 'follow_up')
    """)

    logger.info("Migrated all legacy lead statuses to new pipeline values")

    # ------------------------------------------------------------------
    # Step 3: Update server default
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE leads
        ALTER COLUMN lead_status SET DEFAULT 'awaiting_skip_trace'
    """)

    logger.info("Updated lead_status server default to awaiting_skip_trace")


def downgrade():
    # Reverse the server default
    op.execute("""
        ALTER TABLE leads
        ALTER COLUMN lead_status SET DEFAULT 'new'
    """)

    # Map new values back to old ones (best-effort)
    reverse_map = {
        'skip_trace': 'active',
        'awaiting_skip_trace': 'new',
        'mailing_no_contact_made': 'active',
        'mailing_contacted_no_interest': 'follow_up',
        'mailing_contacted_interested': 'follow_up',
        'negotiating_remote': 'under_contract',
        'in_person_appointment': 'active',
        'offer_delivered': 'active',
        'deprioritize': 'nurture',
        'deal_won': 'closed',
        'deal_lost': 'suppressed',
    }
    for new_val, old_val in reverse_map.items():
        op.execute(f"""
            UPDATE leads SET lead_status = '{old_val}'
            WHERE lead_status = '{new_val}'
        """)

    # Note: PostgreSQL does not support removing enum values — the new values
    # remain in the type definition but are no longer used.
    logger.info("Downgrade complete — new enum values remain in type but are unmapped")
