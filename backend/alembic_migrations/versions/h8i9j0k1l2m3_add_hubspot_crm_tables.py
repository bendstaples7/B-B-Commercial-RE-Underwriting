"""add_hubspot_crm_tables

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-14 00:00:00.000000

Changes:
  Phase 1 — Internal CRM Foundation:
    - organizations (org_type_enum, org_status_enum)
    - organization_audit_log
    - property_organization_links
    - owner_organization_links
    - interactions (interaction_type_enum, interaction_source_enum)
    - interaction_associations (interaction_target_type_enum)
    - tasks (task_status_enum, task_priority_enum, task_source_enum)
    - task_associations (task_target_type_enum)

  Phase 2 — HubSpot Raw Import Tables:
    - hubspot_config
    - hubspot_import_runs (import_run_status_enum)
    - hubspot_deals
    - hubspot_contacts
    - hubspot_companies
    - hubspot_engagements
    - hubspot_matches (match_confidence_enum, match_status_enum)
    - hubspot_signals (hubspot_signal_type_enum)
    - hubspot_signal_dictionary
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'h8i9j0k1l2m3'
down_revision = 'g7h8i9j0k1l2'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. Create all enum types first (PostgreSQL requires them before use)
    # ------------------------------------------------------------------

    # Organization enums
    org_type_enum = sa.Enum(
        'llc', 'trust', 'corporation', 'brokerage',
        'law_firm', 'property_management', 'unknown',
        name='org_type_enum'
    )
    org_type_enum.create(op.get_bind(), checkfirst=True)

    org_status_enum = sa.Enum(
        'active', 'inactive', 'unknown',
        name='org_status_enum'
    )
    org_status_enum.create(op.get_bind(), checkfirst=True)

    # Interaction enums
    interaction_type_enum = sa.Enum(
        'note', 'call', 'email', 'meeting', 'other',
        name='interaction_type_enum'
    )
    interaction_type_enum.create(op.get_bind(), checkfirst=True)

    interaction_source_enum = sa.Enum(
        'manual', 'hubspot_import',
        name='interaction_source_enum'
    )
    interaction_source_enum.create(op.get_bind(), checkfirst=True)

    interaction_target_type_enum = sa.Enum(
        'lead', 'organization', 'contact',
        name='interaction_target_type_enum'
    )
    interaction_target_type_enum.create(op.get_bind(), checkfirst=True)

    # Task enums
    task_status_enum = sa.Enum(
        'open', 'completed', 'cancelled', 'overdue',
        name='task_status_enum'
    )
    task_status_enum.create(op.get_bind(), checkfirst=True)

    task_priority_enum = sa.Enum(
        'high', 'medium', 'low',
        name='task_priority_enum'
    )
    task_priority_enum.create(op.get_bind(), checkfirst=True)

    task_source_enum = sa.Enum(
        'manual', 'hubspot_import',
        name='task_source_enum'
    )
    task_source_enum.create(op.get_bind(), checkfirst=True)

    task_target_type_enum = sa.Enum(
        'lead', 'organization',
        name='task_target_type_enum'
    )
    task_target_type_enum.create(op.get_bind(), checkfirst=True)

    # HubSpot import run enum
    import_run_status_enum = sa.Enum(
        'running', 'success', 'partial', 'failed',
        name='import_run_status_enum'
    )
    import_run_status_enum.create(op.get_bind(), checkfirst=True)

    # HubSpot match enums
    match_confidence_enum = sa.Enum(
        'HIGH', 'MEDIUM', 'LOW', 'UNMATCHED',
        name='match_confidence_enum'
    )
    match_confidence_enum.create(op.get_bind(), checkfirst=True)

    match_status_enum = sa.Enum(
        'pending', 'confirmed', 'rejected',
        name='match_status_enum'
    )
    match_status_enum.create(op.get_bind(), checkfirst=True)

    # HubSpot signal enum
    hubspot_signal_type_enum = sa.Enum(
        'PRIOR_INTERACTION_EXISTS', 'PRIOR_RESPONSE_EXISTS', 'PRIOR_WARM_CONVERSATION',
        'ASKING_PRICE_GIVEN', 'APPOINTMENT_OCCURRED', 'OFFER_PREVIOUSLY_SENT',
        'SELLER_SAID_MAYBE_LATER', 'SELLER_NOT_INTERESTED', 'WRONG_NUMBER',
        'DO_NOT_CONTACT', 'FOLLOW_UP_OVERDUE', 'PRIOR_LEAD_SOURCE_KNOWN',
        name='hubspot_signal_type_enum'
    )
    hubspot_signal_type_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Create tables (dependency order: parents before children)
    # ------------------------------------------------------------------

    # --- organizations ---
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('org_type', postgresql.ENUM(
            'llc', 'trust', 'corporation', 'brokerage',
            'law_firm', 'property_management', 'unknown',
            name='org_type_enum', create_type=False
        ), nullable=False),
        sa.Column('status', postgresql.ENUM(
            'active', 'inactive', 'unknown',
            name='org_status_enum', create_type=False
        ), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(100), nullable=True),
        sa.Column('hubspot_company_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organizations_hubspot_company_id', 'organizations', ['hubspot_company_id'])

    # --- organization_audit_log ---
    op.create_table(
        'organization_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('changed_by', sa.String(100), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organization_audit_log_organization_id', 'organization_audit_log', ['organization_id'])

    # --- property_organization_links ---
    op.create_table(
        'property_organization_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['property_id'], ['leads.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_property_organization_links_property_id', 'property_organization_links', ['property_id'])
    op.create_index('ix_property_organization_links_organization_id', 'property_organization_links', ['organization_id'])

    # --- owner_organization_links ---
    op.create_table(
        'owner_organization_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['owner_id'], ['leads.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_owner_organization_links_owner_id', 'owner_organization_links', ['owner_id'])
    op.create_index('ix_owner_organization_links_organization_id', 'owner_organization_links', ['organization_id'])

    # --- interactions ---
    op.create_table(
        'interactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interaction_type', postgresql.ENUM(
            'note', 'call', 'email', 'meeting', 'other',
            name='interaction_type_enum', create_type=False
        ), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('source', postgresql.ENUM(
            'manual', 'hubspot_import',
            name='interaction_source_enum', create_type=False
        ), nullable=False),
        sa.Column('hubspot_engagement_id', sa.String(50), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.Column('is_orphaned', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_engagement_id', name='uq_interactions_hubspot_engagement_id'),
    )
    op.create_index('ix_interactions_hubspot_engagement_id', 'interactions', ['hubspot_engagement_id'])

    # --- interaction_associations ---
    op.create_table(
        'interaction_associations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interaction_id', sa.Integer(), nullable=False),
        sa.Column('target_type', postgresql.ENUM(
            'lead', 'organization', 'contact',
            name='interaction_target_type_enum', create_type=False
        ), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['interaction_id'], ['interactions.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interaction_associations_interaction_id', 'interaction_associations', ['interaction_id'])
    op.create_index('ix_interaction_assoc_target', 'interaction_associations', ['target_type', 'target_id'])

    # --- tasks ---
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('status', postgresql.ENUM(
            'open', 'completed', 'cancelled', 'overdue',
            name='task_status_enum', create_type=False
        ), nullable=False),
        sa.Column('priority', postgresql.ENUM(
            'high', 'medium', 'low',
            name='task_priority_enum', create_type=False
        ), nullable=False),
        sa.Column('source', postgresql.ENUM(
            'manual', 'hubspot_import',
            name='task_source_enum', create_type=False
        ), nullable=False),
        sa.Column('hubspot_task_id', sa.String(50), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.Column('completion_timestamp', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_task_id', name='uq_tasks_hubspot_task_id'),
    )
    op.create_index('ix_tasks_hubspot_task_id', 'tasks', ['hubspot_task_id'])

    # --- task_associations ---
    op.create_table(
        'task_associations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('target_type', postgresql.ENUM(
            'lead', 'organization',
            name='task_target_type_enum', create_type=False
        ), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['task_id'], ['tasks.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_associations_task_id', 'task_associations', ['task_id'])
    op.create_index('ix_task_assoc_target', 'task_associations', ['target_type', 'target_id'])

    # --- hubspot_config ---
    op.create_table(
        'hubspot_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('portal_id', sa.String(50), nullable=True),
        sa.Column('account_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- hubspot_import_runs ---
    op.create_table(
        'hubspot_import_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('object_type', sa.String(50), nullable=False),
        sa.Column('status', postgresql.ENUM(
            'running', 'success', 'partial', 'failed',
            name='import_run_status_enum', create_type=False
        ), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('total_fetched', sa.Integer(), nullable=False),
        sa.Column('created_count', sa.Integer(), nullable=False),
        sa.Column('updated_count', sa.Integer(), nullable=False),
        sa.Column('skipped_count', sa.Integer(), nullable=False),
        sa.Column('error_count', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- hubspot_deals ---
    op.create_table(
        'hubspot_deals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hubspot_id', sa.String(50), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('import_run_id', sa.Integer(), nullable=True),
        sa.Column('first_imported_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['import_run_id'], ['hubspot_import_runs.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_id', name='uq_hubspot_deals_hubspot_id'),
    )
    op.create_index('ix_hubspot_deals_hubspot_id', 'hubspot_deals', ['hubspot_id'])

    # --- hubspot_contacts ---
    op.create_table(
        'hubspot_contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hubspot_id', sa.String(50), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('import_run_id', sa.Integer(), nullable=True),
        sa.Column('first_imported_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['import_run_id'], ['hubspot_import_runs.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_id', name='uq_hubspot_contacts_hubspot_id'),
    )
    op.create_index('ix_hubspot_contacts_hubspot_id', 'hubspot_contacts', ['hubspot_id'])

    # --- hubspot_companies ---
    op.create_table(
        'hubspot_companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hubspot_id', sa.String(50), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('import_run_id', sa.Integer(), nullable=True),
        sa.Column('first_imported_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['import_run_id'], ['hubspot_import_runs.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_id', name='uq_hubspot_companies_hubspot_id'),
    )
    op.create_index('ix_hubspot_companies_hubspot_id', 'hubspot_companies', ['hubspot_id'])

    # --- hubspot_engagements ---
    op.create_table(
        'hubspot_engagements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hubspot_id', sa.String(50), nullable=False),
        sa.Column('engagement_type', sa.String(50), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('import_run_id', sa.Integer(), nullable=True),
        sa.Column('first_imported_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['import_run_id'], ['hubspot_import_runs.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_id', name='uq_hubspot_engagements_hubspot_id'),
    )
    op.create_index('ix_hubspot_engagements_hubspot_id', 'hubspot_engagements', ['hubspot_id'])

    # --- hubspot_matches ---
    op.create_table(
        'hubspot_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hubspot_record_type', sa.String(50), nullable=False),
        sa.Column('hubspot_id', sa.String(50), nullable=False),
        sa.Column('internal_record_type', sa.String(50), nullable=True),
        sa.Column('internal_record_id', sa.Integer(), nullable=True),
        sa.Column('confidence', postgresql.ENUM(
            'HIGH', 'MEDIUM', 'LOW', 'UNMATCHED',
            name='match_confidence_enum', create_type=False
        ), nullable=False),
        sa.Column('status', postgresql.ENUM(
            'pending', 'confirmed', 'rejected',
            name='match_status_enum', create_type=False
        ), nullable=False),
        sa.Column('matching_criteria', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hubspot_record_type', 'hubspot_id', name='uq_hubspot_match'),
    )
    op.create_index('ix_hubspot_matches_hubspot_id', 'hubspot_matches', ['hubspot_id'])

    # --- hubspot_signals ---
    op.create_table(
        'hubspot_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('signal_type', postgresql.ENUM(
            'PRIOR_INTERACTION_EXISTS', 'PRIOR_RESPONSE_EXISTS', 'PRIOR_WARM_CONVERSATION',
            'ASKING_PRICE_GIVEN', 'APPOINTMENT_OCCURRED', 'OFFER_PREVIOUSLY_SENT',
            'SELLER_SAID_MAYBE_LATER', 'SELLER_NOT_INTERESTED', 'WRONG_NUMBER',
            'DO_NOT_CONTACT', 'FOLLOW_UP_OVERDUE', 'PRIOR_LEAD_SOURCE_KNOWN',
            name='hubspot_signal_type_enum', create_type=False
        ), nullable=False),
        sa.Column('source_engagement_id', sa.String(50), nullable=True),
        sa.Column('extracted_at', sa.DateTime(), nullable=False),
        sa.Column('raw_evidence', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['lead_id'], ['leads.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_hubspot_signals_lead_id', 'hubspot_signals', ['lead_id'])

    # --- hubspot_signal_dictionary ---
    op.create_table(
        'hubspot_signal_dictionary',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('signal_type', sa.String(50), nullable=False),
        sa.Column('keywords', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_type', name='uq_hubspot_signal_dictionary_signal_type'),
    )


def downgrade():
    # Drop tables in reverse dependency order (children before parents)

    op.drop_table('hubspot_signal_dictionary')

    op.drop_index('ix_hubspot_signals_lead_id', table_name='hubspot_signals')
    op.drop_table('hubspot_signals')

    op.drop_index('ix_hubspot_matches_hubspot_id', table_name='hubspot_matches')
    op.drop_table('hubspot_matches')

    op.drop_index('ix_hubspot_engagements_hubspot_id', table_name='hubspot_engagements')
    op.drop_table('hubspot_engagements')

    op.drop_index('ix_hubspot_companies_hubspot_id', table_name='hubspot_companies')
    op.drop_table('hubspot_companies')

    op.drop_index('ix_hubspot_contacts_hubspot_id', table_name='hubspot_contacts')
    op.drop_table('hubspot_contacts')

    op.drop_index('ix_hubspot_deals_hubspot_id', table_name='hubspot_deals')
    op.drop_table('hubspot_deals')

    op.drop_table('hubspot_import_runs')
    op.drop_table('hubspot_config')

    op.drop_index('ix_task_assoc_target', table_name='task_associations')
    op.drop_index('ix_task_associations_task_id', table_name='task_associations')
    op.drop_table('task_associations')

    op.drop_index('ix_tasks_hubspot_task_id', table_name='tasks')
    op.drop_table('tasks')

    op.drop_index('ix_interaction_assoc_target', table_name='interaction_associations')
    op.drop_index('ix_interaction_associations_interaction_id', table_name='interaction_associations')
    op.drop_table('interaction_associations')

    op.drop_index('ix_interactions_hubspot_engagement_id', table_name='interactions')
    op.drop_table('interactions')

    op.drop_index('ix_owner_organization_links_organization_id', table_name='owner_organization_links')
    op.drop_index('ix_owner_organization_links_owner_id', table_name='owner_organization_links')
    op.drop_table('owner_organization_links')

    op.drop_index('ix_property_organization_links_organization_id', table_name='property_organization_links')
    op.drop_index('ix_property_organization_links_property_id', table_name='property_organization_links')
    op.drop_table('property_organization_links')

    op.drop_index('ix_organization_audit_log_organization_id', table_name='organization_audit_log')
    op.drop_table('organization_audit_log')

    op.drop_index('ix_organizations_hubspot_company_id', table_name='organizations')
    op.drop_table('organizations')

    # Drop all enum types (PostgreSQL only — no-op on SQLite)
    sa.Enum(name='hubspot_signal_type_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='match_status_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='match_confidence_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='import_run_status_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='task_target_type_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='task_source_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='task_priority_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='task_status_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='interaction_target_type_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='interaction_source_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='interaction_type_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='org_status_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='org_type_enum').drop(op.get_bind(), checkfirst=True)
