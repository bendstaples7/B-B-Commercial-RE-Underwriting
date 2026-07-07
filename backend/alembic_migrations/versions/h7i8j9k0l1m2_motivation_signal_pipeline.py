"""Motivation signal pipeline — signals, prospect candidates, lead denorm columns.

Revision ID: h7i8j9k0l1m2
Revises: g6a7b8c9d0e1
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h7i8j9k0l1m2'
down_revision = 'g6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TYPE motivation_signal_type_enum AS ENUM (
            'TAX_SCAVENGER_SALE',
            'TAX_ANNUAL_SALE',
            'CHICAGO_SCOFFLAW',
            'BUILDING_VIOLATION',
            'MANUAL_PRIORITY',
            'NOTES_KEYWORD',
            'SOURCE_TYPE_DISTRESS',
            'HUBSPOT_MOTIVATION',
            'TAX_EXEMPT',
            'ASSESSMENT_APPEAL'
        )
    """)
    op.execute("""
        CREATE TYPE motivation_severity_enum AS ENUM ('low', 'medium', 'high')
    """)
    op.execute("""
        CREATE TYPE motivation_signal_source_enum AS ENUM (
            'cook_county_enrichment',
            'ingestion',
            'notes',
            'hubspot',
            'prospect_feed'
        )
    """)
    op.execute("""
        CREATE TYPE prospect_candidate_status_enum AS ENUM (
            'pending', 'approved', 'rejected', 'imported', 'duplicate'
        )
    """)

    op.create_table(
        'motivation_signals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column(
            'signal_type',
            postgresql.ENUM(name='motivation_signal_type_enum', create_type=False),
            nullable=False,
        ),
        sa.Column(
            'severity',
            postgresql.ENUM(name='motivation_severity_enum', create_type=False),
            nullable=False,
        ),
        sa.Column('points', sa.Float(), nullable=False, server_default='0'),
        sa.Column(
            'source',
            postgresql.ENUM(name='motivation_signal_source_enum', create_type=False),
            nullable=False,
        ),
        sa.Column('source_dataset', sa.String(64), nullable=True),
        sa.Column('evidence_key', sa.String(255), nullable=True),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('detected_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.UniqueConstraint('lead_id', 'signal_type', 'evidence_key', name='uq_motivation_signal_lead_type_key'),
    )

    op.create_table(
        'prospect_candidates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_user_id', sa.String(36), nullable=False, index=True),
        sa.Column('pin', sa.String(50), nullable=True, index=True),
        sa.Column('property_street', sa.String(500), nullable=True),
        sa.Column('property_city', sa.String(100), nullable=True),
        sa.Column('property_state', sa.String(50), nullable=True),
        sa.Column('primary_signal_type', sa.String(64), nullable=False),
        sa.Column('motivation_score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_feed', sa.String(64), nullable=False),
        sa.Column('external_key', sa.String(255), nullable=False),
        sa.Column(
            'status',
            postgresql.ENUM(name='prospect_candidate_status_enum', create_type=False),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('duplicate_lead_id', sa.Integer(), sa.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('imported_lead_id', sa.Integer(), sa.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(36), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('raw_record', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('source_feed', 'external_key', name='uq_prospect_feed_external_key'),
    )

    op.create_table(
        'prospect_feed_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feed_name', sa.String(64), nullable=False, unique=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('cursor', sa.String(255), nullable=True),
        sa.Column('rows_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
    )

    op.add_column('leads', sa.Column('motivation_score', sa.Float(), nullable=True, server_default='0'))
    op.add_column('leads', sa.Column('motivation_signal_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_leads_motivation_score', 'leads', ['motivation_score'])


def downgrade():
    op.drop_index('ix_leads_motivation_score', table_name='leads')
    op.drop_column('leads', 'motivation_signal_summary')
    op.drop_column('leads', 'motivation_score')
    op.drop_table('prospect_feed_state')
    op.drop_table('prospect_candidates')
    op.drop_table('motivation_signals')
    op.execute('DROP TYPE IF EXISTS prospect_candidate_status_enum')
    op.execute('DROP TYPE IF EXISTS motivation_signal_source_enum')
    op.execute('DROP TYPE IF EXISTS motivation_severity_enum')
    op.execute('DROP TYPE IF EXISTS motivation_signal_type_enum')
