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
    # Expand lead_status_enum by RECREATING the type (transaction-safe).
    #
    # The previous implementation used ``ALTER TYPE ... ADD VALUE`` and then
    # referenced the new values in UPDATE statements within the same migration.
    # PostgreSQL forbids using a newly-added enum value in the same transaction
    # that added it, so the migration toggled ``raw_conn.autocommit = True`` to
    # commit the ADD VALUEs first.  That fails on a clean fresh-DB upgrade with
    # ``set_session cannot be used inside a transaction`` (Alembic already has
    # an open transaction), and a separate connection cannot see the enum type
    # because it was created earlier in the same uncommitted transaction.
    #
    # Recreating the type — convert the column to TEXT, remap the data, swap in
    # a freshly-created enum with the full value set — avoids ADD VALUE entirely
    # and runs cleanly inside Alembic's transaction on a fresh or existing DB.
    # ------------------------------------------------------------------

    # 1. Drop the server default (it references the old enum) and convert the
    #    column to TEXT so the data can be remapped without enum restrictions.
    op.execute("ALTER TABLE leads ALTER COLUMN lead_status DROP DEFAULT")
    op.execute("ALTER TABLE leads ALTER COLUMN lead_status TYPE TEXT USING lead_status::text")

    # 2. Migrate existing data — highest-priority rules first (plain TEXT now).

    # 2a. Leads with a confirmed HubSpot deal match: derive status from stored stage label
    for stage_label, status_val in _HS_STAGE_TO_STATUS.items():
        op.execute(f"""
            UPDATE leads
            SET lead_status = '{status_val}'
            WHERE lead_status IN ('new', 'active', 'follow_up', 'nurture', 'under_contract', 'closed')
              AND hubspot_deal_stage = '{stage_label}'
        """)

    # 2b. under_contract → negotiating_remote (any remaining)
    op.execute("UPDATE leads SET lead_status = 'negotiating_remote' WHERE lead_status = 'under_contract'")
    # 2c. closed → deal_won (any remaining)
    op.execute("UPDATE leads SET lead_status = 'deal_won' WHERE lead_status = 'closed'")
    # 2d. nurture → deprioritize
    op.execute("UPDATE leads SET lead_status = 'deprioritize' WHERE lead_status = 'nurture'")
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

    # 3. Swap the enum type: rename old → create new (full value set) → convert
    #    the column → drop old.  All transaction-safe.
    op.execute("ALTER TYPE lead_status_enum RENAME TO lead_status_enum_old")
    op.execute("""
        CREATE TYPE lead_status_enum AS ENUM (
            'skip_trace', 'awaiting_skip_trace', 'mailing_no_contact_made',
            'mailing_contacted_no_interest', 'mailing_contacted_interested',
            'negotiating_remote', 'in_person_appointment', 'offer_delivered',
            'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact'
        )
    """)
    op.execute(
        "ALTER TABLE leads ALTER COLUMN lead_status TYPE lead_status_enum "
        "USING lead_status::lead_status_enum"
    )
    op.execute("DROP TYPE lead_status_enum_old")

    # 4. Set the new server default
    op.execute("ALTER TABLE leads ALTER COLUMN lead_status SET DEFAULT 'awaiting_skip_trace'")

    logger.info("Recreated lead_status_enum with pipeline values; default = awaiting_skip_trace")


def downgrade():
    # Reverse the expansion by recreating the original enum type.
    # Convert to TEXT, remap new → old values, swap back to the original enum.

    op.execute("ALTER TABLE leads ALTER COLUMN lead_status DROP DEFAULT")
    op.execute("ALTER TABLE leads ALTER COLUMN lead_status TYPE TEXT USING lead_status::text")

    # Map new values back to old ones (best-effort).
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
        op.execute(f"UPDATE leads SET lead_status = '{old_val}' WHERE lead_status = '{new_val}'")

    # Recreate the original enum type and convert the column back.
    op.execute("ALTER TYPE lead_status_enum RENAME TO lead_status_enum_new")
    op.execute("""
        CREATE TYPE lead_status_enum AS ENUM (
            'new', 'active', 'follow_up', 'nurture',
            'under_contract', 'closed', 'suppressed', 'do_not_contact'
        )
    """)
    op.execute(
        "ALTER TABLE leads ALTER COLUMN lead_status TYPE lead_status_enum "
        "USING lead_status::lead_status_enum"
    )
    op.execute("DROP TYPE lead_status_enum_new")
    op.execute("ALTER TABLE leads ALTER COLUMN lead_status SET DEFAULT 'new'")

    logger.info("Downgrade complete — restored original lead_status_enum values")
