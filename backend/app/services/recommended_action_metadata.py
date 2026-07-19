"""Labels and explanations for unified recommended actions."""

from app.services.outreach_method_service import (
    outreach_action_explanation,
    outreach_action_label,
)
from app.services.scoring_rubric import (
    contacts_likely_prior_owner,
    contacts_need_post_hold_verification,
)

# Shared copy for skip-trace after a recent transfer (hold + active skip-trace work).
RECENT_SALE_OUTDATED_CONTACT_EXPLANATION = (
    'Because of a recent sale, the owner and mailing details on file are likely '
    'tied to the prior owner — treat that contact info as outdated until skip '
    'trace confirms who to reach now.'
)

RECOMMENDED_ACTION_METADATA = {
    'enrich_data': {
        'label': 'Enrich Data',
        'explanation': (
            'Next step is to fill gaps that block scoring or outreach — typically '
            'a property match / street address, owner-entity research, or a low '
            'overall score (Tier D). Phones and emails alone do not clear this action.'
        ),
    },
    'enrich_data_recently_sold': {
        'label': 'Confirm New Owner',
        'explanation': (
            'The two-year mail hold has ended. Move this lead to skip trace '
            '(or finish skip trace) so outreach targets the current owner. '
            + RECENT_SALE_OUTDATED_CONTACT_EXPLANATION
        ),
    },
    'resolve_match': {
        'label': 'Resolve Property Match',
        'explanation': 'No property record has been matched to this lead. Search for the property or research the PIN to enable analysis.',
    },
    'analyze_property': {
        'label': 'Analyze Property',
        'explanation': 'A property match exists but no analysis has been run. Run a property analysis to get an ARV estimate and investment scenarios.',
    },
    'follow_up_now': {
        'label': 'Follow Up Now',
        'explanation': 'This lead has prior engagement or an overdue follow-up. Reach out now to keep the conversation warm.',
    },
    'ready_for_outreach': {
        'label': 'Ready for Outreach',
        'explanation': 'This lead has a high score and complete analysis. It is ready for direct outreach — call, mail, or add to a marketing batch.',
    },
    'add_contact_info': {
        'label': 'Add Contact Info',
        'explanation': (
            'No reachable contact method is on file for this lead. '
            'Add a phone, email, or mailing address, or finish skip trace before outreach.'
        ),
    },
    'create_task': {
        'label': 'Create a Task',
        'explanation': 'This lead has no open tasks and no specific next action. Create a task to define the next concrete step.',
    },
    'nurture': {
        'label': 'Quick actions',
        'explanation': '',
    },
    'suppress': {
        'label': 'Suppress',
        'explanation': 'This lead does not meet investment criteria. Suppress it to remove it from active queues.',
    },
    'do_not_contact': {
        'label': 'Do Not Contact',
        'explanation': 'This lead has requested no contact. No outreach actions are permitted.',
    },
    'review_now': {
        'label': 'Review Now',
        'explanation': 'This lead has a solid score and good data quality. Review it for immediate outreach.',
    },
    'mail_ready': {
        'label': 'Mail Ready',
        'explanation': 'High-tier lead with complete data — ready for a mail campaign.',
    },
    'call_ready': {
        'label': 'Call Ready',
        'explanation': 'This lead is ready for a phone outreach attempt.',
    },
    'hold': {
        'label': 'Skip Trace Hold',
        'explanation': (
            'A recent sale is still inside the two-year hold. Keep this lead in '
            'Skip Trace until its scheduled Awaiting Skip Trace date. '
            + RECENT_SALE_OUTDATED_CONTACT_EXPLANATION
        ),
    },
    'valuation_needed': {
        'label': 'Valuation Needed',
        'explanation': 'Run a valuation or property analysis before outreach.',
    },
    'needs_manual_review': {
        'label': 'Needs Manual Review',
        'explanation': (
            'Building ownership or other factors need attention. '
            'Review the Building ownership section on this page — '
            'no separate confirm action is required when analysis is already complete.'
        ),
    },
}

TASK_TYPE_TO_RECOMMENDED_ACTION = {
    'run_property_analysis': 'analyze_property',
    'match_hubspot_deal': 'resolve_match',
    'skip_trace_owner': 'enrich_data',
    'add_to_mail_batch': 'ready_for_outreach',
    'call_owner_today': 'follow_up_now',
    'research_missing_pin': 'resolve_match',
    'confirm_building_ownership': 'needs_manual_review',
}


WINNING_RULE_LABELS = {
    'no_property_match_no_address': 'No matched property and no street address on file',
    'research_entity_owner': 'Owner is an unresolved entity — research before cold mail',
    'is_warm': 'Lead is marked warm from prior engagement',
    'engaged_pipeline_nurture': (
        'Engaged pipeline status — stay in relationship; call when appropriate'
    ),
    'tier_d_contactable': (
        'Lead score is Tier D but a phone is on file — nurture / call, not enrich'
    ),
    'tier_d_mailable': (
        'Lead score is Tier D but mailable — nurture rather than enrich'
    ),
    'tier_d': 'Lead score is Tier D with no reachable contact channel',
    'follow_up_overdue': 'Follow-up is overdue',
    'do_not_contact': 'Lead is marked do not contact',
    'terminal_status': 'Lead is in a terminal pipeline status',
    'likely_condo': 'Commercial lead flagged as likely condo',
    'condo_needs_review': 'Condo / building ownership needs review',
    'condo_partial_ambiguous': 'Partial condo status is ambiguous',
    'skip_trace_status': 'Lead is in skip-trace status without enough contact info',
    'no_contact_info': 'No phone, email, or mailable address on file',
    'mailable_no_digital_contact': 'Mailable but no phone or email',
    'no_property_match_with_address': 'Has an address but no confirmed property match',
    'mail_work_in_flight': 'Mail work is already in progress',
    'recently_sold': 'Property was recently sold — prior-owner contact info is likely outdated',
    'recent_sale_hold': (
        'Recent-sale hold — prior-owner contact info is likely outdated until skip trace'
    ),
    'tier_a_high_quality': 'Tier A with high data quality',
    'tier_b_high_quality': 'Tier B with high data quality',
    'high_motivation_tier_b': 'Tier B with high motivation',
    'high_score_no_tasks': 'High score with no open tasks',
    'high_motivation_high_score': 'High score and high motivation',
    'tier_c': 'Tier C — nurture for later',
    'no_tasks_create_one': 'No open tasks — create a next step',
    'has_open_tasks': 'Has open tasks — continue current work',
    'negative_motivation': 'Negative motivation score',
    'institutional_owner': 'Institutional owner — cold mail blocked',
    'nonprofit_organization': 'Nonprofit owner — cold mail blocked',
    'tax_exempt_owner': 'Tax-exempt owner — cold mail blocked',
}


def get_winning_rule_label(rule: str | None) -> str | None:
    if not rule:
        return None
    return WINNING_RULE_LABELS.get(rule, rule.replace('_', ' '))


def _lead_needs_recent_sale_contact_rationale(lead) -> bool:
    """True when Next Steps should explain outdated pre-sale owner/mailing info."""
    if lead is None:
        return False
    status = getattr(lead, 'lead_status', None)
    if status not in ('skip_trace', 'awaiting_skip_trace'):
        return False
    if not (
        contacts_likely_prior_owner(lead)
        or contacts_need_post_hold_verification(lead)
    ):
        return False
    return bool(getattr(lead, 'needs_skip_trace', False))


def _with_recent_sale_contact_rationale(
    explanation: str | None,
    *,
    lead=None,
    winning_rule: str | None = None,
    action: str | None = None,
) -> str | None:
    """Append (or set) recent-sale outdated-contact copy on the existing explanation."""
    needs = (
        action == 'hold'
        or winning_rule in ('recent_sale_hold', 'recently_sold')
        or _lead_needs_recent_sale_contact_rationale(lead)
    )
    if not needs:
        return explanation
    # `hold` already embeds the copy in its base metadata.
    if action == 'hold':
        return explanation
    base = (explanation or '').strip()
    if RECENT_SALE_OUTDATED_CONTACT_EXPLANATION in base:
        return explanation if explanation else RECENT_SALE_OUTDATED_CONTACT_EXPLANATION
    if not base:
        return RECENT_SALE_OUTDATED_CONTACT_EXPLANATION
    return f'{base} {RECENT_SALE_OUTDATED_CONTACT_EXPLANATION}'


def get_recommended_action_display(
    action: str | None,
    contact_method: str | None = None,
    *,
    lead=None,
    winning_rule: str | None = None,
) -> dict:
    """Return label and explanation, with channel-specific overrides when applicable."""
    if not action:
        return {'label': None, 'explanation': None}

    metadata = RECOMMENDED_ACTION_METADATA.get(action, {})
    base_label = metadata.get('label')
    base_explanation = metadata.get('explanation')

    # Post-hold prior-owner path: clearer than generic "Enrich Data".
    if action == 'enrich_data' and winning_rule == 'recently_sold':
        sold_meta = RECOMMENDED_ACTION_METADATA['enrich_data_recently_sold']
        base_label = sold_meta['label']
        base_explanation = sold_meta['explanation']

    channel_label = outreach_action_label(action, contact_method)
    label = channel_label or base_label

    explanation = outreach_action_explanation(action, contact_method, base_explanation)
    explanation = _with_recent_sale_contact_rationale(
        explanation,
        lead=lead,
        winning_rule=winning_rule,
        action=action,
    )
    return {'label': label, 'explanation': explanation}
