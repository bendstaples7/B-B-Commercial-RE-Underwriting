"""multifamily schema

Revision ID: c3d4e5f6g7h8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. lender_profiles (no FK dependencies)
    op.create_table(
        'lender_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_by_user_id', sa.String(length=255), nullable=False),
        sa.Column('company', sa.String(length=200), nullable=False),
        sa.Column('lender_type', sa.String(length=30), nullable=False),
        sa.Column('origination_fee_rate', sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column('prepay_penalty_description', sa.Text(), nullable=True),
        # Construction_To_Perm fields
        sa.Column('ltv_total_cost', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('construction_rate', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('construction_io_months', sa.Integer(), nullable=True),
        sa.Column('construction_term_months', sa.Integer(), nullable=True),
        sa.Column('perm_rate', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('perm_amort_years', sa.Integer(), nullable=True),
        sa.Column('min_interest_or_yield', sa.Numeric(precision=14, scale=2), nullable=True),
        # Self_Funded_Reno fields
        sa.Column('max_purchase_ltv', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('treasury_5y_rate', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('spread_bps', sa.Integer(), nullable=True),
        sa.Column('term_years', sa.Integer(), nullable=True),
        sa.Column('amort_years', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "lender_type IN ('Construction_To_Perm', 'Self_Funded_Reno')",
            name='ck_lender_profiles_lender_type',
        ),
    )
    op.create_index('ix_lender_profiles_created_by_user_id', 'lender_profiles', ['created_by_user_id'])

    # 2. deals (no FK to other new tables)
    op.create_table(
        'deals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_by_user_id', sa.String(length=255), nullable=False),
        sa.Column('property_address', sa.String(length=500), nullable=False),
        sa.Column('property_city', sa.String(length=100), nullable=True),
        sa.Column('property_state', sa.String(length=50), nullable=True),
        sa.Column('property_zip', sa.String(length=20), nullable=True),
        sa.Column('unit_count', sa.Integer(), nullable=False),
        sa.Column('purchase_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('closing_costs', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('close_date', sa.Date(), nullable=True),
        sa.Column('vacancy_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.05'),
        sa.Column('other_income_monthly', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('management_fee_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.08'),
        sa.Column('reserve_per_unit_per_year', sa.Numeric(precision=14, scale=2), nullable=False, server_default='250'),
        sa.Column('property_taxes_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('insurance_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('utilities_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('repairs_and_maintenance_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('admin_and_marketing_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('payroll_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('other_opex_annual', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('interest_reserve_amount', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('custom_cap_rate', sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('unit_count >= 5', name='ck_deals_unit_count_min'),
        sa.CheckConstraint('purchase_price > 0', name='ck_deals_purchase_price_positive'),
    )
    op.create_index('ix_deals_created_by_user_id', 'deals', ['created_by_user_id'])
    op.create_index('ix_deals_property_address', 'deals', ['property_address'])

    # 3. units (FK -> deals)
    op.create_table(
        'units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('unit_identifier', sa.String(length=50), nullable=False),
        sa.Column('unit_type', sa.String(length=50), nullable=True),
        sa.Column('beds', sa.Integer(), nullable=True),
        sa.Column('baths', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('sqft', sa.Integer(), nullable=True),
        sa.Column('occupancy_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('deal_id', 'unit_identifier', name='uq_units_deal_unit_identifier'),
        sa.CheckConstraint(
            "occupancy_status IN ('Occupied', 'Vacant', 'Down')",
            name='ck_units_occupancy_status',
        ),
    )
    op.create_index('ix_units_deal_id', 'units', ['deal_id'])

    # 4. rent_roll_entries (FK -> units, one-to-one)
    op.create_table(
        'rent_roll_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('current_rent', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('lease_start_date', sa.Date(), nullable=True),
        sa.Column('lease_end_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('unit_id', name='uq_rent_roll_entries_unit_id'),
        sa.CheckConstraint(
            'lease_end_date >= lease_start_date',
            name='ck_rent_roll_entries_lease_dates',
        ),
    )

    # 5. rehab_plan_entries (FK -> units, one-to-one)
    op.create_table(
        'rehab_plan_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('renovate_flag', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('current_rent', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('suggested_post_reno_rent', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('underwritten_post_reno_rent', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('rehab_start_month', sa.Integer(), nullable=True),
        sa.Column('downtime_months', sa.Integer(), nullable=True),
        sa.Column('stabilized_month', sa.Integer(), nullable=True),
        sa.Column('rehab_budget', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('scope_notes', sa.Text(), nullable=True),
        sa.Column('stabilizes_after_horizon', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('unit_id', name='uq_rehab_plan_entries_unit_id'),
        sa.CheckConstraint(
            'rehab_start_month IS NULL OR (rehab_start_month >= 1 AND rehab_start_month <= 24)',
            name='ck_rehab_plan_entries_start_month_range',
        ),
        sa.CheckConstraint(
            'downtime_months IS NULL OR downtime_months >= 0',
            name='ck_rehab_plan_entries_downtime_non_negative',
        ),
    )

    # 6. market_rent_assumptions (FK -> deals)
    op.create_table(
        'market_rent_assumptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('unit_type', sa.String(length=50), nullable=False),
        sa.Column('target_rent', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('post_reno_target_rent', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('deal_id', 'unit_type', name='uq_market_rent_assumptions_deal_unit_type'),
    )

    # 7. rent_comps (FK -> deals)
    op.create_table(
        'rent_comps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=500), nullable=False),
        sa.Column('neighborhood', sa.String(length=200), nullable=True),
        sa.Column('unit_type', sa.String(length=50), nullable=False),
        sa.Column('observed_rent', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sqft', sa.Integer(), nullable=False),
        sa.Column('rent_per_sqft', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('observation_date', sa.Date(), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.CheckConstraint('sqft > 0', name='ck_rent_comps_sqft_positive'),
    )
    op.create_index('ix_rent_comps_deal_id', 'rent_comps', ['deal_id'])

    # 8. sale_comps (FK -> deals)
    op.create_table(
        'sale_comps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=500), nullable=False),
        sa.Column('unit_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('sale_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('close_date', sa.Date(), nullable=True),
        sa.Column('observed_cap_rate', sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column('observed_ppu', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('distance_miles', sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.CheckConstraint('unit_count > 0', name='ck_sale_comps_unit_count_positive'),
        sa.CheckConstraint(
            'observed_cap_rate > 0 AND observed_cap_rate <= 0.25',
            name='ck_sale_comps_cap_rate_range',
        ),
    )
    op.create_index('ix_sale_comps_deal_id', 'sale_comps', ['deal_id'])

    # 9. deal_lender_selections (FK -> deals, lender_profiles)
    op.create_table(
        'deal_lender_selections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('lender_profile_id', sa.Integer(), nullable=False),
        sa.Column('scenario', sa.String(length=1), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lender_profile_id'], ['lender_profiles.id'], ondelete='CASCADE'),
        sa.UniqueConstraint(
            'deal_id', 'scenario', 'lender_profile_id',
            name='uq_deal_lender_selections_deal_scenario_profile',
        ),
        sa.CheckConstraint("scenario IN ('A', 'B')", name='ck_deal_lender_selections_scenario'),
    )
    # Partial unique index: at most one primary lender per (deal_id, scenario)
    op.create_index(
        'ix_deal_lender_selections_primary',
        'deal_lender_selections',
        ['deal_id', 'scenario'],
        unique=True,
        postgresql_where=sa.text('is_primary = true'),
    )

    # 10. funding_sources (FK -> deals)
    op.create_table(
        'funding_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=10), nullable=False),
        sa.Column('total_available', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('interest_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0'),
        sa.Column('origination_fee_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('deal_id', 'source_type', name='uq_funding_sources_deal_source_type'),
        sa.CheckConstraint(
            "source_type IN ('Cash', 'HELOC_1', 'HELOC_2')",
            name='ck_funding_sources_source_type',
        ),
    )

    # 11. pro_forma_results (FK -> deals, one-to-one cache)
    op.create_table(
        'pro_forma_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('inputs_hash', sa.String(length=64), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('deal_id', name='uq_pro_forma_results_deal_id'),
    )

    # 12. lead_deal_links (FK -> leads, deals)
    op.create_table(
        'lead_deal_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('lead_id', 'deal_id', name='uq_lead_deal_links_lead_deal'),
    )
    op.create_index('ix_lead_deal_links_lead_id', 'lead_deal_links', ['lead_id'])
    op.create_index('ix_lead_deal_links_deal_id', 'lead_deal_links', ['deal_id'])

    # 13. deal_audit_trails (FK -> deals)
    op.create_table(
        'deal_audit_trails',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('changed_fields', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_deal_audit_trails_deal_id', 'deal_audit_trails', ['deal_id'])


def downgrade():
    # Drop tables in reverse dependency order
    op.drop_table('deal_audit_trails')
    op.drop_table('lead_deal_links')
    op.drop_table('pro_forma_results')
    op.drop_table('funding_sources')
    op.drop_table('deal_lender_selections')
    op.drop_table('sale_comps')
    op.drop_table('rent_comps')
    op.drop_table('market_rent_assumptions')
    op.drop_table('rehab_plan_entries')
    op.drop_table('rent_roll_entries')
    op.drop_table('units')
    op.drop_table('deals')
    op.drop_table('lender_profiles')
