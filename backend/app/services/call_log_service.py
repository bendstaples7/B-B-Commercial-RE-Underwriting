"""CallLogService — native call and note logging for leads."""
import logging
import re
from datetime import datetime, date, timezone

from app import db
from app.models import Lead, LeadTimelineEntry
from app.exceptions import (
    DoNotContactViolationError,
    LeadTaskValidationError,
)

logger = logging.getLogger(__name__)

VALID_CALL_OUTCOMES = frozenset(['answered', 'voicemail', 'no_answer', 'busy', 'wrong_number', 'not_interested'])


def _contact_display_name(contact) -> str | None:
    if contact is None:
        return None
    parts = [contact.first_name, contact.last_name]
    name = ' '.join(p for p in parts if p)
    return name or None


def _format_phone_display(phone_number: str | None) -> str | None:
    if not phone_number:
        return None
    digits = re.sub(r'\D', '', phone_number)
    if len(digits) == 10:
        return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'({digits[1:4]}) {digits[4:7]}-{digits[7:]}'
    return phone_number


def _validate_contact_for_lead(lead_id: int, contact_id: int | None) -> None:
    if contact_id is None:
        return
    from app.models.property_contact import PropertyContact
    link = PropertyContact.query.filter_by(property_id=lead_id, contact_id=contact_id).first()
    if link is None:
        raise LeadTaskValidationError(
            f"Contact {contact_id} is not linked to lead {lead_id}.",
            field='contact_id',
        )


def _validate_contact_phone_for_lead(
    lead_id: int,
    contact_id: int | None,
    contact_phone_id: int | None,
) -> None:
    if contact_phone_id is None:
        return
    from app.models.contact_phone import ContactPhone
    phone = ContactPhone.query.get(contact_phone_id)
    if phone is None:
        raise LeadTaskValidationError(
            f"Contact phone {contact_phone_id} not found.",
            field='contact_phone_id',
        )
    if contact_id is not None and phone.contact_id != contact_id:
        raise LeadTaskValidationError(
            f"Contact phone {contact_phone_id} does not belong to contact {contact_id}.",
            field='contact_phone_id',
        )
    _validate_contact_for_lead(lead_id, phone.contact_id)


def _validate_contact_email_for_lead(
    lead_id: int,
    contact_id: int | None,
    contact_email_id: int | None,
) -> None:
    if contact_email_id is None:
        return
    from app.models.contact_email import ContactEmail
    email = ContactEmail.query.get(contact_email_id)
    if email is None:
        raise LeadTaskValidationError(
            f"Contact email {contact_email_id} not found.",
            field='contact_email_id',
        )
    if contact_id is not None and email.contact_id != contact_id:
        raise LeadTaskValidationError(
            f"Contact email {contact_email_id} does not belong to contact {contact_id}.",
            field='contact_email_id',
        )
    _validate_contact_for_lead(lead_id, email.contact_id)


def _resolve_contact_name(lead_id: int, contact_id: int | None) -> str | None:
    if contact_id is None:
        return None
    _validate_contact_for_lead(lead_id, contact_id)
    from app.models.contact import Contact
    return _contact_display_name(Contact.query.get(contact_id))


def _build_call_summary(
    outcome: str,
    duration_minutes: int | None,
    notes: str | None,
    contact_name: str | None,
    phone_number: str | None,
    phone_label: str | None,
) -> str:
    phone_display = _format_phone_display(phone_number)
    if contact_name:
        method_suffix = ''
        if phone_display:
            method_suffix = f' ({phone_display}'
            if phone_label:
                method_suffix += f', {phone_label}'
            method_suffix += ')'
        summary_parts = [f'Call with {contact_name}{method_suffix}: {outcome}']
    elif phone_display:
        label_suffix = f', {phone_label}' if phone_label else ''
        summary_parts = [f'Call ({phone_display}{label_suffix}): {outcome}']
    else:
        summary_parts = [f'Call logged: {outcome}']

    if duration_minutes:
        summary_parts.append(f'{duration_minutes} min')
    if notes:
        summary_parts.append(notes[:200])
    return '. '.join(summary_parts)[:500]


def _build_email_summary(
    body: str,
    subject: str | None,
    contact_name: str | None,
    email_address: str | None,
    email_label: str | None,
) -> str:
    subject_text = (subject or '').strip()
    if not subject_text and body.startswith('[Email]'):
        first_line = body.split('\n', 1)[0]
        subject_text = first_line.replace('[Email]', '').strip()

    if contact_name:
        method_suffix = ''
        if email_address:
            method_suffix = f' ({email_address}'
            if email_label:
                method_suffix += f', {email_label}'
            method_suffix += ')'
        prefix = f'Email to {contact_name}{method_suffix}'
        if subject_text:
            return f'{prefix}: {subject_text}'[:500]
        return f'{prefix}: {body[:400]}'[:500]

    if email_address:
        label_suffix = f', {email_label}' if email_label else ''
        prefix = f'Email ({email_address}{label_suffix})'
        if subject_text:
            return f'{prefix}: {subject_text}'[:500]
        return f'{prefix}: {body[:400]}'[:500]

    return body[:500]


def _mail_attribution_eligible(lead_id: int, mail_campaign_id: int, actor_user_id: str) -> bool:
    from app.models import MailCampaign, MailQueueItem

    campaign = MailCampaign.query.get(mail_campaign_id)
    if campaign is None or campaign.created_by != actor_user_id:
        return False
    return MailQueueItem.query.filter_by(
        campaign_id=mail_campaign_id,
        lead_id=lead_id,
        status='sent',
    ).first() is not None


class CallLogService:
    """Handles logging calls and notes on leads."""

    def log_call(
        self,
        lead_id: int,
        outcome: str,
        duration_minutes: int | None,
        notes: str | None,
        actor: str = 'anonymous',
        contact_id: int | None = None,
        contact_phone_id: int | None = None,
        phone_number: str | None = None,
        phone_label: str | None = None,
        mail_campaign_id: int | None = None,
    ) -> LeadTimelineEntry:
        """Log a call on a lead."""
        if outcome not in VALID_CALL_OUTCOMES:
            raise LeadTaskValidationError(
                f"Invalid call outcome '{outcome}'. Must be one of: {', '.join(sorted(VALID_CALL_OUTCOMES))}",
                field='outcome',
            )

        if duration_minutes is not None and not (1 <= duration_minutes <= 999):
            raise LeadTaskValidationError(
                "Call duration must be between 1 and 999 minutes.",
                field='duration_minutes',
            )

        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        if lead.lead_status == 'do_not_contact':
            raise DoNotContactViolationError(lead_id)

        _validate_contact_for_lead(lead_id, contact_id)
        _validate_contact_phone_for_lead(lead_id, contact_id, contact_phone_id)
        contact_name = _resolve_contact_name(lead_id, contact_id)

        if outcome == 'answered':
            lead.last_contact_date = date.today()
        elif outcome in ('voicemail', 'no_answer'):
            lead.unanswered_call_count = (lead.unanswered_call_count or 0) + 1

        _CONTACTED_NO_INTEREST_OUTCOMES = {'not_interested'}
        if (outcome in _CONTACTED_NO_INTEREST_OUTCOMES
                and lead.lead_status in ('awaiting_skip_trace', 'mailing_no_contact_made', 'skip_trace')):
            lead.lead_status = 'mailing_contacted_no_interest'

        db.session.add(lead)

        summary = _build_call_summary(
            outcome, duration_minutes, notes, contact_name, phone_number, phone_label,
        )

        metadata = {
            'outcome': outcome,
            'duration_minutes': duration_minutes,
            'notes': notes,
        }
        if contact_id is not None:
            metadata['contact_id'] = contact_id
        if contact_name:
            metadata['contact_name'] = contact_name
        if contact_phone_id is not None:
            metadata['contact_phone_id'] = contact_phone_id
        if phone_number:
            metadata['phone_number'] = phone_number
        if phone_label:
            metadata['phone_label'] = phone_label
        attributed_to_mail = (
            mail_campaign_id is not None
            and _mail_attribution_eligible(lead_id, mail_campaign_id, actor)
        )
        if attributed_to_mail:
            metadata['mail_campaign_id'] = mail_campaign_id
            metadata['attributed_to_mail'] = True

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='call_logged',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=summary,
            event_metadata=metadata,
        )
        db.session.add(entry)
        db.session.commit()

        try:
            from app.services.phone_confidence_service import PhoneConfidenceService
            PhoneConfidenceService.update_from_call(
                lead_id,
                outcome,
                contact_phone_id=contact_phone_id,
                phone_number=phone_number,
            )
            db.session.commit()
        except Exception as exc:
            logger.error(
                "PhoneConfidenceService.update_from_call failed for lead %s: %s",
                lead_id, exc, exc_info=True,
            )

        try:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead_id)
        except Exception as exc:
            logger.error(
                "refresh_lead_scoring failed for lead %s after call log: %s",
                lead_id, exc, exc_info=True,
            )

        if attributed_to_mail:
            try:
                from app.services.mail_campaign_service import MailCampaignService
                MailCampaignService().record_call_attribution(mail_campaign_id, lead_id, actor)
            except Exception as exc:
                logger.warning(
                    'Mail call attribution failed for lead %s campaign %s: %s',
                    lead_id, mail_campaign_id, exc,
                )

        return entry

    def log_note(
        self,
        lead_id: int,
        body: str,
        actor: str = 'anonymous',
        contact_id: int | None = None,
        contact_email_id: int | None = None,
        email_address: str | None = None,
        email_label: str | None = None,
        subject: str | None = None,
    ) -> LeadTimelineEntry:
        """Log a note on a lead."""
        if not body or not body.strip():
            raise LeadTaskValidationError("Note body cannot be empty.", field='body')

        if len(body) > 5000:
            raise LeadTaskValidationError(
                "Note body cannot exceed 5,000 characters.",
                field='body',
            )

        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        if lead.lead_status == 'do_not_contact':
            raise DoNotContactViolationError(lead_id)

        _validate_contact_for_lead(lead_id, contact_id)
        _validate_contact_email_for_lead(lead_id, contact_id, contact_email_id)
        contact_name = _resolve_contact_name(lead_id, contact_id)

        has_email_context = any([
            contact_email_id, email_address, email_label, subject,
        ])
        if has_email_context or body.strip().startswith('[Email]'):
            summary = _build_email_summary(body, subject, contact_name, email_address, email_label)
        else:
            summary = body[:500]

        metadata: dict = {'body': body}
        if subject:
            metadata['subject'] = subject
        if contact_id is not None:
            metadata['contact_id'] = contact_id
        if contact_name:
            metadata['contact_name'] = contact_name
        if contact_email_id is not None:
            metadata['contact_email_id'] = contact_email_id
        if email_address:
            metadata['email_address'] = email_address
        if email_label:
            metadata['email_label'] = email_label

        is_email = has_email_context or body.strip().startswith('[Email]')
        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='email_logged' if is_email else 'note_added',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=summary,
            event_metadata=metadata,
        )
        db.session.add(entry)
        db.session.commit()

        try:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead_id)
        except Exception as exc:
            logger.error(
                "refresh_lead_scoring failed for lead %s after note log: %s",
                lead_id, exc, exc_info=True,
            )

        return entry
