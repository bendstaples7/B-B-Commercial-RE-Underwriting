"""Add CRM columns to leads table for Actionable Lead Command Center.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-20 00:00:00.000000

Changes:
  - Drop old `recommended_action` column (uses legacy recommended_action_enum)
  - Create new PostgreSQL enum `lead_status_enum` with 8 values
  - Create new PostgreSQL enum `crm_recommended_action_enum` with 10 values
  - Add `lead_status` column (lead_status_enum, NOT NULL, server_default='new')
  - Add `recommended_action` column (crm_recommended_action_enum, nullable)
  - Add boolean signal columns: has_phone, has_email, has_property_match,
    analysis_complete, follow_up_overdue, is_warm, review_required
  - Add scalar signal columns: data_completeness_score, unanswered_call_count
  - Add date/datetime columns: last_contact_date, last_hubspot_sync_at,
    follow_up_date, review_triggered_at
  - Add string columns: hubspot_deal_stage, review_reason
  - Add composite indexes:
      ix_leads_status_action (lead_status, recommended_action)
      ix_leads_status_property_match (lead_status, has_property_match)
      ix_leads_overdue_status (follow_up_overdue, lead_status)

Requirements: Phase 1, Task 1.1 — Actionable Lead Command Center
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'm3n4o5p6q7r8'
down_revision = 'l2m3n4o5p6q7'
branch_labels = None
depends_on = None

# New enum definitions
_LEAD_STATUS_ENUM_NAME = 'lead_status_enum'
_LEAD_STATUS_VALUES = (
    'new', 'active', 'follow_up', 'nurture',
    'under_contract', 'closed', 'suppressed', 'do_not_contact',
)

_CRM_RA_ENUM_NAME = 'crm_recommended_action_enum'
_CRM_RA_VALUES = (
    'enrich_data', 'resolve_match', 'analyze_property', 'follow_up_now',
    'ready_for_outreach', 'add_contact_info', 'create_task', 'nurture',
    'suppress', 'do_not_contact',
)

# Legacy enum (used by the old recommended_action column added in i9j0k1l2m3n4)
_LEGACY_RA_ENUM_NAME = 'recommended_action_enum'
_LEGACY_RA_VALUES = ('CONTACT_NOW', 'FOLLOW_UP_LATER', 'REVISIT_OFFER', 'DO_NOT_CONTACT')


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Drop the legacy recommended_action column (uses old enum values)
    # ------------------------------------------------------------------
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('recommended_action')

    # Drop the legacy enum type now that no column references it
    legacy_ra_enum = postgresql.ENUM(*_LEGACY_RA_VALUES, name=_LEGACY_RA_ENUM_NAME)
    legacy_ra_enum.drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Create new enum types
    # ------------------------------------------------------------------
    lead_status_enum = postgresql.ENUM(*_LEAD_STATUS_VALUES, name=_LEAD_STATUS_ENUM_NAME)
    lead_status_enum.create(bind, checkfirst=True)

    crm_ra_enum = postgresql.ENUM(*_CRM_RA_VALUES, name=_CRM_RA_ENUM_NAME)
    crm_ra_enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 3. Add new columns to leads table
    # ------------------------------------------------------------------
    with op.batch_alter_table('leads', schema=None) as batch_op:
        # Lead lifecycle status — NOT NULL with server_default so existing rows
        # are backfilled to 'new' without a separate UPDATE statement.
        batch_op.add_column(
            sa.Column(
                'lead_status',
                sa.Enum(*_LEAD_STATUS_VALUES, name=_LEAD_STATUS_ENUM_NAME),
                nullable=False,
                server_default='new',
            )
        )

        # New recommended_action with CRM enum values
        batch_op.add_column(
            sa.Column(
                'recommended_action',
                sa.Enum(*_CRM_RA_VALUES, name=_CRM_RA_ENUM_NAME),
                nullable=True,
            )
        )

        # Boolean signal columns — NOT NULL with server_default FALSE
        batch_op.add_column(
            sa.Column('has_phone', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('has_email', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('has_property_match', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('analysis_complete', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('follow_up_overdue', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('is_warm', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )
        batch_op.add_column(
            sa.Column('review_required', sa.Boolean(), nullable=False, server_default=sa.text('FALSE'))
        )

        # Scalar signal columns
        batch_op.add_column(
            sa.Column('data_completeness_score', sa.Float(), nullable=False, server_default=sa.text('0.0'))
        )
        batch_op.add_column(
            sa.Column('unanswered_call_count', sa.Integer(), nullable=False, server_default=sa.text('0'))
        )

        # Date / datetime columns — nullable
        batch_op.add_column(
            sa.Column('last_contact_date', sa.Date(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('last_hubspot_sync_at', sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('follow_up_date', sa.Date(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('review_triggered_at', sa.DateTime(), nullable=True)
        )

        # String columns — nullable
        batch_op.add_column(
            sa.Column('hubspot_deal_stage', sa.String(100), nullable=True)
        )
        batch_op.add_column(
            sa.Column('review_reason', sa.String(255), nullable=True)
        )

        # Single-column indexes on the two enum columns
        batch_op.create_index('ix_leads_lead_status', ['lead_status'])
        batch_op.create_index('ix_leads_recommended_action', ['recommended_action'])

    # ------------------------------------------------------------------
    # 4. Composite indexes (created outside batch_alter_table so they use
    #    op.create_index directly, which is cleaner for multi-column indexes)
    # ------------------------------------------------------------------
    op.create_index(
        'ix_leads_status_action',
        'leads',
        ['lead_status', 'recommended_action'],
    )
    op.create_index(
        'ix_leads_status_property_match',
        'leads',
        ['lead_status', 'has_property_match'],
    )
    op.create_index(
        'ix_leads_overdue_status',
        'leads',
        ['follow_up_overdue', 'lead_status'],
    )

    # ------------------------------------------------------------------
    # 5. Backfill boolean signal columns from existing data
    #
    # These UPDATE statements run immediately after the columns are added
    # so that existing rows are never left in an invalid default state.
    # New rows inserted after this migration will be kept in sync by the
    # application layer (LeadScoringEngine, HubSpotTimelineImportService).
    # ------------------------------------------------------------------
    conn = op.get_bind()

    # has_phone: TRUE if any of phone_1..phone_7 is non-empty, or a
    # ContactPhone record exists via property_contacts
    conn.execute(sa.text("""
        UPDATE leads
        SET has_phone = TRUE
        WHERE (
            (phone_1 IS NOT NULL AND phone_1 != '')
            OR (phone_2 IS NOT NULL AND phone_2 != '')
            OR (phone_3 IS NOT NULL AND phone_3 != '')
            OR (phone_4 IS NOT NULL AND phone_4 != '')
            OR (phone_5 IS NOT NULL AND phone_5 != '')
            OR (phone_6 IS NOT NULL AND phone_6 != '')
            OR (phone_7 IS NOT NULL AND phone_7 != '')
            OR EXISTS (
                SELECT 1 FROM property_contacts pc
                JOIN contact_phones cp ON cp.contact_id = pc.contact_id
                WHERE pc.property_id = leads.id
            )
        )
    """))

    # has_email: TRUE if any of email_1..email_5 is non-empty, or a
    # ContactEmail record exists via property_contacts
    conn.execute(sa.text("""
        UPDATE leads
        SET has_email = TRUE
        WHERE (
            (email_1 IS NOT NULL AND email_1 != '')
            OR (email_2 IS NOT NULL AND email_2 != '')
            OR (email_3 IS NOT NULL AND email_3 != '')
            OR (email_4 IS NOT NULL AND email_4 != '')
            OR (email_5 IS NOT NULL AND email_5 != '')
            OR EXISTS (
                SELECT 1 FROM property_contacts pc
                JOIN contact_emails ce ON ce.contact_id = pc.contact_id
                WHERE pc.property_id = leads.id
            )
        )
    """))

    # has_property_match: TRUE if a confirmed HubSpot match exists for this lead
    conn.execute(sa.text("""
        UPDATE leads
        SET has_property_match = TRUE
        WHERE EXISTS (
            SELECT 1 FROM hubspot_matches hm
            WHERE hm.internal_record_id = leads.id
            AND hm.internal_record_type = 'lead'
            AND hm.status = 'confirmed'
        )
    """))


def downgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Drop composite indexes
    # ------------------------------------------------------------------
    op.drop_index('ix_leads_overdue_status', table_name='leads')
    op.drop_index('ix_leads_status_property_match', table_name='leads')
    op.drop_index('ix_leads_status_action', table_name='leads')

    # ------------------------------------------------------------------
    # 2. Drop new columns (including single-column indexes)
    # ------------------------------------------------------------------
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index('ix_leads_recommended_action')
        batch_op.drop_index('ix_leads_lead_status')

        batch_op.drop_column('review_reason')
        batch_op.drop_column('hubspot_deal_stage')
        batch_op.drop_column('review_triggered_at')
        batch_op.drop_column('follow_up_date')
        batch_op.drop_column('last_hubspot_sync_at')
        batch_op.drop_column('last_contact_date')
        batch_op.drop_column('unanswered_call_count')
        batch_op.drop_column('data_completeness_score')
        batch_op.drop_column('review_required')
        batch_op.drop_column('is_warm')
        batch_op.drop_column('follow_up_overdue')
        batch_op.drop_column('analysis_complete')
        batch_op.drop_column('has_property_match')
        batch_op.drop_column('has_email')
        batch_op.drop_column('has_phone')
        batch_op.drop_column('recommended_action')
        batch_op.drop_column('lead_status')

    # ------------------------------------------------------------------
    # 3. Drop new enum types
    # ------------------------------------------------------------------
    crm_ra_enum = postgresql.ENUM(*_CRM_RA_VALUES, name=_CRM_RA_ENUM_NAME)
    crm_ra_enum.drop(bind, checkfirst=True)

    lead_status_enum = postgresql.ENUM(*_LEAD_STATUS_VALUES, name=_LEAD_STATUS_ENUM_NAME)
    lead_status_enum.drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 4. Restore the legacy recommended_action column and its enum type
    # ------------------------------------------------------------------
    legacy_ra_enum = postgresql.ENUM(*_LEGACY_RA_VALUES, name=_LEGACY_RA_ENUM_NAME)
    legacy_ra_enum.create(bind, checkfirst=True)

    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'recommended_action',
                sa.Enum(*_LEGACY_RA_VALUES, name=_LEGACY_RA_ENUM_NAME),
                nullable=True,
            )
        )
