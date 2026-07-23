"""Lead and LeadAuditTrail models."""
from app import db
from datetime import datetime, date
from app.models.json_types import JSONBCompatible
from sqlalchemy import event, select, or_


class Property(db.Model):
    """Property model representing a property owner who is a potential seller or marketing target."""
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)

    # Property details
    property_street = db.Column(db.String(500), nullable=True)
    normalized_street = db.Column(db.String(500), nullable=True, index=True)
    property_city = db.Column(db.String(100), nullable=True)
    property_state = db.Column(db.String(50), nullable=True)
    property_zip = db.Column(db.String(20), nullable=True)
    property_type = db.Column(db.String(50), nullable=True)
    assessor_class = db.Column(db.String(10), nullable=True)
    bedrooms = db.Column(db.Integer, nullable=True)
    bathrooms = db.Column(db.Float, nullable=True)
    square_footage = db.Column(db.Integer, nullable=True)
    lot_size = db.Column(db.Integer, nullable=True)
    year_built = db.Column(db.Integer, nullable=True)

    # Owner information
    owner_first_name = db.Column(db.String(128), nullable=True)
    owner_last_name = db.Column(db.String(128), nullable=True)
    ownership_type = db.Column(db.String(100), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=True)

    # Contact information
    phone_1 = db.Column(db.Text, nullable=True)
    phone_2 = db.Column(db.Text, nullable=True)
    phone_3 = db.Column(db.Text, nullable=True)
    email_1 = db.Column(db.String(255), nullable=True)
    email_2 = db.Column(db.String(255), nullable=True)

    # Mailing information
    mailing_address = db.Column(db.String(500), nullable=True)
    mailing_city = db.Column(db.String(100), nullable=True, index=True)
    mailing_state = db.Column(db.String(50), nullable=True, index=True)
    mailing_zip = db.Column(db.String(20), nullable=True, index=True)

    # Research tracking
    source = db.Column(db.String(100), nullable=True)  # where the property was found
    deal_source = db.Column(db.String(255), nullable=True)  # how/where deal was sourced (e.g. Cityscape)
    deal_description = db.Column(db.Text, nullable=True)  # free-text deal context from CRM or manual entry
    date_identified = db.Column(db.Date, nullable=True)  # when it was found
    notes = db.Column(db.Text, nullable=True)  # general notes

    # Skip tracing
    needs_skip_trace = db.Column(db.Boolean, nullable=True, default=False)
    skip_tracer = db.Column(db.String(100), nullable=True)
    date_skip_traced = db.Column(db.Date, nullable=True)
    # Multi-source ladder (canonical attempts in skip_trace_attempts)
    skip_trace_next_source_id = db.Column(db.String(64), nullable=True)
    skip_trace_exhausted_at = db.Column(db.DateTime, nullable=True)
    skip_trace_cycle = db.Column(db.Integer, nullable=False, default=1, server_default='1')

    # CRM integration
    date_added_to_hubspot = db.Column(db.Date, nullable=True)

    # Additional property details
    units = db.Column(db.Integer, nullable=True)
    units_allowed = db.Column(db.Integer, nullable=True)
    zoning = db.Column(db.String(100), nullable=True)
    county_assessor_pin = db.Column(db.String(50), nullable=True)
    tax_bill_2021 = db.Column(db.Float, nullable=True)
    most_recent_sale = db.Column(db.String(255), nullable=True)

    # Enrichment — assessed value and recent sale price (from assessor data sources)
    assessed_value = db.Column(db.Float, nullable=True)
    most_recent_sale_price = db.Column(db.Float, nullable=True)

    # Second owner
    owner_2_first_name = db.Column(db.String(128), nullable=True)
    owner_2_last_name = db.Column(db.String(128), nullable=True)

    # Additional address
    address_2 = db.Column(db.String(500), nullable=True)
    returned_addresses = db.Column(db.Text, nullable=True)

    # Additional phones (phone_1 through phone_3 already exist)
    phone_4 = db.Column(db.Text, nullable=True)
    phone_5 = db.Column(db.Text, nullable=True)
    phone_6 = db.Column(db.Text, nullable=True)
    phone_7 = db.Column(db.Text, nullable=True)

    # Additional emails (email_1 and email_2 already exist)
    email_3 = db.Column(db.String(255), nullable=True)
    email_4 = db.Column(db.String(255), nullable=True)
    email_5 = db.Column(db.String(255), nullable=True)

    # Social media
    socials = db.Column(db.Text, nullable=True)

    # Mailing tracking
    # Legacy flag — prefer recommended_action == 'mail_ready' + MailQueueItem membership.
    # Still cleared on send/remove for stale rows; new enqueue paths should not set True.
    up_next_to_mail = db.Column(db.Boolean, nullable=True, default=False)
    mailer_history = db.Column(db.JSON, nullable=True)  # JSONB for flexible mailer tracking

    # Lead classification
    lead_category = db.Column(db.String(50), nullable=False, default='residential', server_default='residential', index=True)

    # Scoring
    lead_score = db.Column(db.Float, default=0)

    # HubSpot CRM — suppression flag
    suppression_flag = db.Column(db.Boolean, nullable=False, default=False)

    # Lead lifecycle status — mirrors the HubSpot pipeline stages plus platform-specific values
    lead_status = db.Column(db.Enum(
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
        'suppressed',
        'do_not_contact',
        name='lead_status_enum'
    ), nullable=False, default='skip_trace', server_default='skip_trace', index=True)

    # Action Engine output (unified recommended-action vocabulary)
    recommended_action = db.Column(db.Enum(
        'enrich_data', 'resolve_match', 'analyze_property', 'follow_up_now',
        'ready_for_outreach', 'add_contact_info', 'create_task', 'nurture', 'hold',
        'suppress', 'do_not_contact',
        'review_now', 'mail_ready', 'call_ready', 'valuation_needed',
        'needs_manual_review',
        name='crm_recommended_action_enum'
    ), nullable=True, index=True)

    recommended_contact_method = db.Column(db.Enum(
        'phone', 'email', 'text', 'direct_mail',
        name='recommended_contact_method_enum'
    ), nullable=True, index=True)

    # Action Engine signals
    has_phone = db.Column(db.Boolean, nullable=False, default=False)
    has_email = db.Column(db.Boolean, nullable=False, default=False)
    has_property_match = db.Column(db.Boolean, nullable=False, default=False)
    analysis_complete = db.Column(db.Boolean, nullable=False, default=False)
    follow_up_overdue = db.Column(db.Boolean, nullable=False, default=False)
    is_warm = db.Column(db.Boolean, nullable=False, default=False)
    data_completeness_score = db.Column(db.Float, nullable=False, default=0.0)
    last_contact_date = db.Column(db.Date, nullable=True)
    unanswered_call_count = db.Column(db.Integer, nullable=False, default=0)
    hubspot_deal_stage = db.Column(db.String(100), nullable=True)  # read-only HubSpot mirror; pipeline status is lead_status
    last_hubspot_sync_at = db.Column(db.DateTime, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)

    # Needs Review flag
    review_required = db.Column(db.Boolean, nullable=False, default=False)
    review_reason = db.Column(db.String(255), nullable=True)
    review_triggered_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    data_source = db.Column(db.String(100), nullable=True)
    source_type = db.Column(db.String(50), nullable=True, index=True)
    tax_distress_data = db.Column(JSONBCompatible, nullable=True)
    violation_data = db.Column(JSONBCompatible, nullable=True)
    permit_data = db.Column(JSONBCompatible, nullable=True)
    motivation_score = db.Column(db.Float, nullable=True, default=0.0)
    motivation_signal_summary = db.Column(JSONBCompatible, nullable=True)
    # Latest Command Center quick briefing (Gemini) — bullets + metadata
    quick_briefing = db.Column(JSONBCompatible, nullable=True)
    manual_priority = db.Column(db.Integer, nullable=True)
    last_import_job_id = db.Column(db.Integer, db.ForeignKey('import_jobs.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Owner user link — which platform user owns/manages this lead
    owner_user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True, index=True)

    # Analysis link
    analysis_session_id = db.Column(db.Integer, db.ForeignKey('analysis_sessions.id'), nullable=True)

    # Condo filter
    condo_risk_status = db.Column(db.String(50), nullable=True)
    building_sale_possible = db.Column(db.String(50), nullable=True)
    condo_analysis_id = db.Column(db.Integer, db.ForeignKey('address_group_analyses.id'), nullable=True)

    # Relationships
    analysis_session = db.relationship('AnalysisSession', backref=db.backref('lead', uselist=False), uselist=False, foreign_keys=[analysis_session_id])
    enrichment_records = db.relationship('EnrichmentRecord', backref='lead', lazy='dynamic')
    marketing_list_members = db.relationship('MarketingListMember', backref='lead', lazy='dynamic')
    audit_trail = db.relationship('LeadAuditTrail', backref='lead', lazy='dynamic', cascade='all, delete-orphan')
    last_import_job = db.relationship('ImportJob', backref='leads', foreign_keys=[last_import_job_id])
    property_contacts = db.relationship('PropertyContact', backref='property',
                                        cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<Property {self.property_street}>'


@event.listens_for(Property, 'before_insert')
@event.listens_for(Property, 'before_update')
def _refresh_lead_normalized_street(mapper, connection, target):
    """Keep normalized_street in sync with property_street for dedup enforcement.

    On update, only refresh when property_street itself changed. Mail enqueue
    may fill empty city/state/zip without touching the street; recomputing
    normalized_street on those writes can hit uq_leads_owner_normalized_street
    against a sibling lead with a cleaner street key.
    """
    from sqlalchemy import inspect as sa_inspect

    from app.services.lead_merge_utils import dedup_street_key

    state = sa_inspect(target)
    if state.persistent:
        history = state.attrs.property_street.history
        if not history.has_changes():
            return
    key = dedup_street_key(target.property_street)
    target.normalized_street = key or None


# Backward-compatibility alias — defined immediately after Property so it is
# available even if the module is only partially loaded during circular imports.
Lead = Property


class LeadAuditTrail(db.Model):
    """Audit trail for tracking changes to lead records."""
    __tablename__ = 'lead_audit_trail'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False, index=True)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.String(100), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<LeadAuditTrail lead_id={self.lead_id} field={self.field_name}>'


# ---------------------------------------------------------------------------
# Delete-time cleanup hook — prevent orphaned HubSpot references on lead delete
# ---------------------------------------------------------------------------
#
# WHY A HOOK AND NOT A FOREIGN KEY:
#   HubSpotMatch.internal_record_id, InteractionAssociation.target_id, and
#   TaskAssociation.target_id are POLYMORPHIC — each is paired with a *_type
#   discriminator column ('lead' vs 'organization'/'contact'), so a single id
#   column may reference a lead OR a different entity. A SQL foreign key (and
#   therefore ON DELETE CASCADE) can only target one parent table, so it cannot
#   be used here. A SQLAlchemy ``before_delete`` mapper event is the right
#   mechanism for the application's own ORM deletes.
#
# SCOPE / LIMITATION:
#   This listener fires only for ORM-level deletes that load the instance and
#   call ``session.delete(lead)`` (the path the app's own code uses). It does
#   NOT fire for bulk ``Query.delete()`` (e.g. ``Lead.query.filter(...).delete()``)
#   or raw SQL deletes, both of which bypass the unit-of-work and never emit
#   per-instance mapper events. The Bug 4 / Bug 5 sync-time healing in
#   ``run_hubspot_matching`` / ``run_convert_hubspot_activities`` remains the
#   catch-all safety net for those bulk/SQL/manual deletions.
#
# IMPLEMENTATION NOTE:
#   We are mid-flush inside this event, so we MUST issue Core statements through
#   the ``connection`` argument against the models' ``__table__`` constructs —
#   NOT ORM session operations (which would re-enter the flush) and NOT
#   hardcoded table-name strings (real table/column names are resolved from the
#   model metadata so a future rename can't silently break this). Booleans are
#   set via Core ``.values(is_orphaned=True)`` so the literal renders correctly
#   on both SQLite (1) and PostgreSQL (TRUE).
@event.listens_for(Property, 'before_delete')
def _cleanup_hubspot_refs_before_lead_delete(mapper, connection, target):
    """Reset/strip HubSpot references that polymorphically point at this lead."""
    lead_id = target.id
    if lead_id is None:
        return

    # Imported lazily so this module carries no import-time dependency on the
    # HubSpot/activity models and so the real table/column metadata is resolved
    # at delete time.
    from app.models.hubspot_match import HubSpotMatch
    from app.models.interaction import Interaction
    from app.models.interaction_association import InteractionAssociation
    from app.models.task_association import TaskAssociation

    hubspot_matches = HubSpotMatch.__table__
    interactions = Interaction.__table__
    interaction_assocs = InteractionAssociation.__table__
    task_assocs = TaskAssociation.__table__

    # 1. Reset this lead's HubSpot matches so they re-match on the next sync.
    #    Confirmed and pending matches are reset to 'pending' with a NULL
    #    internal_record_id; 'rejected' matches are deliberately left untouched
    #    to preserve reviewer decisions.
    connection.execute(
        hubspot_matches.update()
        .where(hubspot_matches.c.internal_record_type == 'lead')
        .where(hubspot_matches.c.internal_record_id == lead_id)
        .where(hubspot_matches.c.status.in_(['confirmed', 'pending']))
        .values(status='pending', internal_record_id=None)
    )

    # 2. Mark interactions associated with this lead as orphaned, THEN drop the
    #    dangling associations. The UPDATE must run first — once the associations
    #    are deleted the subquery would match nothing. The interaction rows
    #    themselves are preserved (only re-flagged + de-associated).
    #
    #    Bug 5/7: an interaction is only orphaned when THIS lead is its *last*
    #    remaining association. An interaction that is also associated with
    #    another lead/entity stays linked (is_orphaned must NOT be set), so it
    #    keeps surfacing on its other association(s).
    affected_interaction_ids = (
        select(interaction_assocs.c.interaction_id)
        .where(interaction_assocs.c.target_type == 'lead')
        .where(interaction_assocs.c.target_id == lead_id)
    )
    # Interactions that retain at least one OTHER association (a different lead,
    # or any non-lead target) must NOT be orphaned.
    still_linked_interaction_ids = (
        select(interaction_assocs.c.interaction_id)
        .where(or_(
            interaction_assocs.c.target_type != 'lead',
            interaction_assocs.c.target_id != lead_id,
        ))
    )
    connection.execute(
        interactions.update()
        .where(interactions.c.id.in_(affected_interaction_ids))
        .where(interactions.c.id.notin_(still_linked_interaction_ids))
        .values(is_orphaned=True)
    )
    connection.execute(
        interaction_assocs.delete()
        .where(interaction_assocs.c.target_type == 'lead')
        .where(interaction_assocs.c.target_id == lead_id)
    )

    # 3. Drop dangling task associations for this lead. The Task rows themselves
    #    remain — only the lead-pointing associations are removed.
    connection.execute(
        task_assocs.delete()
        .where(task_assocs.c.target_type == 'lead')
        .where(task_assocs.c.target_id == lead_id)
    )
