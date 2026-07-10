"""Labels and explanations for unified recommended actions."""

from app.services.outreach_method_service import (
    outreach_action_explanation,
    outreach_action_label,
)

RECOMMENDED_ACTION_METADATA = {
    'enrich_data': {
        'label': 'Enrich Data',
        'explanation': 'This lead is missing key data needed to evaluate it. Add contact info, property details, or run a skip trace to improve data completeness.',
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
        'explanation': 'No phone or email is on file for this lead. Add contact information or run a skip trace before attempting outreach.',
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
    'valuation_needed': {
        'label': 'Valuation Needed',
        'explanation': 'Run a valuation or property analysis before outreach.',
    },
    'needs_manual_review': {
        'label': 'Needs Manual Review',
        'explanation': 'Condo risk or other factors require manual review before proceeding.',
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


def get_recommended_action_display(
    action: str | None,
    contact_method: str | None = None,
) -> dict:
    """Return label and explanation, with channel-specific overrides when applicable."""
    if not action:
        return {'label': None, 'explanation': None}

    metadata = RECOMMENDED_ACTION_METADATA.get(action, {})
    base_label = metadata.get('label')
    base_explanation = metadata.get('explanation')

    channel_label = outreach_action_label(action, contact_method)
    label = channel_label or base_label

    explanation = outreach_action_explanation(action, contact_method, base_explanation)
    return {'label': label, 'explanation': explanation}
