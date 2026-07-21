#!/usr/bin/env python3
"""Heal malformed property addresses, stale recommended_action, and stranded mailers.

Usage:
  python scripts/heal_addresses_and_actions.py --dry-run
  python scripts/heal_addresses_and_actions.py --apply
  python scripts/heal_addresses_and_actions.py --apply --lead-id 10665
  python scripts/heal_addresses_and_actions.py --dry-run --skip-mail
"""
from __future__ import annotations

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()

_STREET_SUFFIX_CITIES = frozenset({
    'AVE', 'AVENUE', 'ST', 'STREET', 'DR', 'DRIVE', 'RD', 'ROAD', 'LN', 'LANE',
    'BLVD', 'BOULEVARD', 'CT', 'COURT', 'CIR', 'CIRCLE', 'TER', 'TERRACE', 'WAY',
    'PL', 'PLACE', 'PKWY', 'PARKWAY',
})


def _looks_malformed(lead) -> bool:
    city = (lead.property_city or '').strip()
    street = (lead.property_street or '').strip()
    zip_code = (lead.property_zip or '').strip()
    if city and city.upper() in _STREET_SUFFIX_CITIES:
        return True
    if city and city.isupper() and city.upper() not in {'CHICAGO', 'IL'}:
        return True
    if street and street.isupper() and len(street) > 8:
        return True
    if street and any(ch.isdigit() for ch in street[-6:]) and (
        street[-5:].isdigit() or street.split()[-1][:5].isdigit()
    ):
        # ZIP likely embedded in street
        tokens = street.split()
        if tokens and tokens[-1][:5].isdigit() and len(tokens[-1]) >= 5:
            return True
    if street and not city and zip_code:
        return True
    if street and not city and not zip_code:
        # May still be completable via ZIP-in-street parse
        tokens = street.split()
        if tokens and tokens[-1][:5].isdigit():
            return True
    return False


def _heal_addresses(*, dry_run: bool, lead_id: int | None, limit: int) -> dict:
    from app import db
    from app.models import Lead
    from app.services.property_address_service import complete_property_address

    q = Lead.query.filter(Lead.property_street.isnot(None), Lead.property_street != '')
    if lead_id is not None:
        q = q.filter(Lead.id == lead_id)
    else:
        q = q.order_by(Lead.id.asc()).limit(max(limit * 5, limit))  # oversample then filter

    scanned = 0
    candidates = []
    for lead in q.all():
        scanned += 1
        if _looks_malformed(lead):
            candidates.append(lead)
            if lead_id is None and len(candidates) >= limit:
                break

    changed = []
    for lead in candidates:
        before = {
            'street': lead.property_street,
            'city': lead.property_city,
            'state': lead.property_state,
            'zip': lead.property_zip,
        }
        if dry_run:
            from app.services.property_address_service import complete_property_address_fields
            preview = complete_property_address_fields(
                lead.property_street,
                lead.property_city,
                lead.property_state,
                lead.property_zip,
                try_gis=False,
            )
            after = {
                'street': preview.get('property_street'),
                'city': preview.get('property_city'),
                'state': preview.get('property_state'),
                'zip': preview.get('property_zip'),
            }
        else:
            result = complete_property_address(
                lead,
                try_gis=True,
                actor='heal_addresses_and_actions',
                commit=False,
                write_timeline=True,
                set_review_flag=False,
            )
            after = {
                'street': result.get('property_street'),
                'city': result.get('property_city'),
                'state': result.get('property_state'),
                'zip': result.get('property_zip'),
            }
        if before != after:
            changed.append({'lead_id': lead.id, 'before': before, 'after': after})

    if not dry_run and changed:
        db.session.commit()

    return {
        'scanned': scanned,
        'candidates': len(candidates),
        'changed': len(changed),
        'rows': changed,
    }


def _heal_dirty_complete_streets(*, dry_run: bool, lead_id: int | None) -> dict:
    """Strip embedded City/State/ZIP left glued onto ``property_street``.

    Targets rows the incomplete-address completer never revisits: the street
    still reads e.g. ``4414 N Campbell Ave Chicago IL 60625`` while the
    city/state/ZIP columns are already populated, so the UI renders the locality
    twice. Uses the *structural* cleaner (no city hint) so a corrupt city column
    can never amputate the real street name.
    """
    from app import db
    from app.models import Lead
    from app.services.property_address_service import (
        street_only_line,
        title_case_address_part,
        _clean,
    )
    from sqlalchemy import func
    from sqlalchemy.exc import IntegrityError

    # ONLY touch rows whose city/state/ZIP columns are already fully populated.
    # For those, embedded locality in the street is redundant and safe to strip.
    # Never run on incomplete rows: the embedded locality is the *only* copy of
    # city/state/ZIP there, and stripping it would destroy that data.
    q = Lead.query.filter(
        Lead.property_street.isnot(None), func.trim(Lead.property_street) != '',
        Lead.property_city.isnot(None), func.trim(Lead.property_city) != '',
        Lead.property_state.isnot(None), func.trim(Lead.property_state) != '',
        Lead.property_zip.isnot(None), func.trim(Lead.property_zip) != '',
    )
    if lead_id is not None:
        q = q.filter(Lead.id == lead_id)

    changed = []
    skipped = []
    scanned = 0
    for lead in q.yield_per(500):
        scanned += 1
        original = _clean(lead.property_street)
        if not original:
            continue
        cleaned = street_only_line(original)
        if not cleaned or cleaned == original or len(cleaned) < 3:
            continue
        new_street = title_case_address_part(cleaned)
        if not new_street or new_street == original:
            continue
        if dry_run:
            changed.append({'lead_id': lead.id, 'before': original, 'after': new_street})
            continue
        # Isolate each write: cleaning the street recomputes normalized_street,
        # which can collide with a genuine duplicate lead (same owner + property)
        # under uq_leads_owner_normalized_street. Skip + report those (they are a
        # dedup concern) so one conflict doesn't abort the whole heal batch.
        sp = db.session.begin_nested()
        try:
            lead.property_street = new_street
            db.session.flush()
            sp.commit()
            changed.append({'lead_id': lead.id, 'before': original, 'after': new_street})
        except IntegrityError:
            sp.rollback()
            db.session.expire(lead, ['property_street', 'normalized_street'])
            skipped.append({'lead_id': lead.id, 'before': original, 'reason': 'dup_owner_normalized_street'})

    if not dry_run and changed:
        db.session.commit()

    return {
        'scanned': scanned,
        'changed': len(changed),
        'skipped': len(skipped),
        'rows': changed,
        'skipped_rows': skipped,
    }


def _heal_recommended_actions(*, dry_run: bool, lead_id: int | None, limit: int) -> dict:
    from app import db
    from app.models import Lead
    from app.services.lead_scoring_engine import LeadScoringEngine
    from app.services.lead_refresh import refresh_lead_scoring

    q = Lead.query
    if lead_id is not None:
        q = q.filter(Lead.id == lead_id)
    else:
        # Focus first on suppress/do_not_contact mismatches and active pipeline.
        q = q.filter(
            Lead.recommended_action.in_(('suppress', 'do_not_contact', 'enrich_data', 'mail_ready'))
        ).order_by(Lead.id.asc()).limit(limit)

    engine = LeadScoringEngine()
    mismatches = []
    leads = q.all()
    for lead in leads:
        try:
            weights = engine.get_weights(lead.owner_user_id or 'default')
            result = engine.compute(lead, weights)
            expected = result.recommended_action
        except Exception as exc:
            mismatches.append({
                'lead_id': lead.id,
                'error': str(exc),
                'stored': lead.recommended_action,
            })
            continue
        if (lead.recommended_action or None) != (expected or None):
            mismatches.append({
                'lead_id': lead.id,
                'stored': lead.recommended_action,
                'expected': expected,
            })
            if not dry_run:
                refresh_lead_scoring(lead.id)

    if not dry_run and mismatches:
        db.session.commit()

    return {
        'checked': len(leads),
        'mismatches': len(mismatches),
        'rows': mismatches[:50],
    }


def _recover_invalid_mail(*, dry_run: bool, lead_id: int | None) -> dict:
    from app import db
    from app.models import MailQueueItem
    from app.services.open_letter_contact_mapper import (
        persist_embedded_address_fields,
        validate_owner_mailing_address,
    )
    from sqlalchemy import and_

    q = MailQueueItem.query.filter(MailQueueItem.status == 'invalid_address')
    if lead_id is not None:
        q = q.filter(MailQueueItem.lead_id == lead_id)

    requeued = []
    refreshed = []
    still_invalid = []

    for item in q.all():
        lead = item.lead
        if lead is None:
            still_invalid.append({'item_id': item.id, 'reason': 'missing_lead'})
            continue
        persist_embedded_address_fields(lead)
        error = validate_owner_mailing_address(lead)
        if error is None:
            # Respect partial unique (user_id, lead_id) WHERE queued.
            existing_queued = (
                MailQueueItem.query.filter(
                    and_(
                        MailQueueItem.user_id == item.user_id,
                        MailQueueItem.lead_id == item.lead_id,
                        MailQueueItem.status == 'queued',
                        MailQueueItem.id != item.id,
                    )
                ).first()
            )
            if existing_queued is not None:
                still_invalid.append({
                    'item_id': item.id,
                    'lead_id': item.lead_id,
                    'reason': 'already_queued_elsewhere',
                })
                continue
            requeued.append({'item_id': item.id, 'lead_id': item.lead_id})
            if not dry_run:
                item.status = 'queued'
                item.validation_error = None
                db.session.add(item)
        else:
            if (item.validation_error or '') != error:
                refreshed.append({
                    'item_id': item.id,
                    'lead_id': item.lead_id,
                    'old': item.validation_error,
                    'new': error,
                })
                if not dry_run:
                    item.validation_error = error
                    db.session.add(item)
            else:
                still_invalid.append({
                    'item_id': item.id,
                    'lead_id': item.lead_id,
                    'reason': error,
                })

    if not dry_run:
        db.session.commit()

    return {
        'requeued': len(requeued),
        'refreshed_errors': len(refreshed),
        'still_invalid': len(still_invalid),
        'requeued_rows': requeued[:30],
        'refreshed_rows': refreshed[:30],
    }


def _heal_skip_trace_todays_action_leaks(*, dry_run: bool, lead_id: int | None) -> dict:
    """Clear dated-due chores on skip_trace leads that re-enter Today's Action.

    Proper Move to Skip Trace clears these chores and sets needs_skip_trace.
    Status-only / hold-sync paths historically left May custom follow-ups open.
    """
    from datetime import date

    from app import db
    from app.models import Lead, LeadTask
    from app.services.skip_trace_enqueue import (
        SkipTraceEnqueue,
        clear_dated_due_chores_entering_skip_trace,
    )

    today = date.today()
    q = Lead.query.filter(Lead.lead_status == 'skip_trace')
    if lead_id is not None:
        q = q.filter(Lead.id == lead_id)

    healed = []
    scanned = 0
    pending_hubspot_ids: set[str] = set()
    handoff_clear_ids: set[str] = set()
    for lead in q.yield_per(200):
        scanned += 1
        open_dated_due = (
            LeadTask.query
            .filter(
                LeadTask.lead_id == lead.id,
                LeadTask.status == 'open',
                LeadTask.due_date.isnot(None),
                LeadTask.due_date <= today,
            )
            .all()
        )
        leak_chores = [
            t for t in open_dated_due
            if t.workflow_key != 'recent_sale_hold'
            and not SkipTraceEnqueue._is_undated_skip_trace_handoff(t)
        ]
        has_hold = (
            LeadTask.query
            .filter_by(lead_id=lead.id, status='open', workflow_key='recent_sale_hold')
            .first()
            is not None
        )
        enqueue = SkipTraceEnqueue()
        has_handoff = enqueue._find_undated_skip_trace_handoff(lead.id) is not None
        needs_flag = bool(lead.needs_skip_trace)

        # Heal when dated leak chores remain, or when skip_trace lacks the
        # proper handoff/flag and is not in a recent-sale hold.
        needs_pipeline = (not has_hold) and (not needs_flag or not has_handoff)
        if not leak_chores and not needs_pipeline:
            continue

        row = {
            'lead_id': lead.id,
            'cleared_chores': len(leak_chores),
            'had_handoff': has_handoff,
            'needs_skip_trace_before': needs_flag,
            'has_recent_sale_hold': has_hold,
        }
        if dry_run:
            healed.append(row)
            continue

        if leak_chores:
            _, hs_ids = clear_dated_due_chores_entering_skip_trace(
                lead.id,
                actor='heal_skip_trace_todays_action',
                reason='heal_skip_trace_todays_action',
                today=today,
            )
            pending_hubspot_ids.update(hs_ids)
        # During active recent-sale hold, keep needs_skip_trace=False.
        if not has_hold:
            lead.needs_skip_trace = True
            # Canonical handoff logic: reuse/convert/create (no duplicate tasks).
            _, clear_ids, extra_hs = enqueue.ensure_awaiting_skip_trace_handoff(
                lead.id,
                actor='heal_skip_trace_todays_action',
                commit=False,
            )
            handoff_clear_ids.update(clear_ids)
            pending_hubspot_ids.update(extra_hs)
        db.session.add(lead)
        healed.append(row)

    if not dry_run and healed:
        db.session.commit()
        if pending_hubspot_ids:
            from app.services.hubspot_task_completion_service import (
                sync_pending_hubspot_completions,
            )
            sync_pending_hubspot_completions(sorted(pending_hubspot_ids))
        if handoff_clear_ids:
            from app.services.hubspot_task_completion_service import (
                sync_hubspot_task_properties,
            )
            for hs_id in sorted(handoff_clear_ids):
                sync_hubspot_task_properties(
                    hs_id,
                    title='Awaiting skip trace',
                    clear_due_date=True,
                )

    return {
        'scanned': scanned,
        'healed': len(healed),
        'rows': healed,
    }


def _heal_generic_owner_contacts(*, dry_run: bool, lead_id: int | None) -> dict:
    """Unlink auto-shared owner Contacts that only exist due to a generic name.

    Never deletes Contacts; only removes PropertyContact links where the contact
    name is generic and linked to more than one property (spurious portfolio).
    """
    from app import db
    from app.models import Contact, PropertyContact
    from app.services.plugins.owner_name_utils import is_generic_owner_name, contact_display_name
    from sqlalchemy import func

    q = (
        db.session.query(Contact.id, Contact.first_name, Contact.last_name, func.count(PropertyContact.id))
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .filter(PropertyContact.role == 'owner')
        .group_by(Contact.id, Contact.first_name, Contact.last_name)
        .having(func.count(PropertyContact.id) > 1)
    )
    unlinked = []
    for cid, first, last, count in q.all():
        display = contact_display_name(first, last)
        if not is_generic_owner_name(display):
            continue
        links = PropertyContact.query.filter_by(contact_id=cid, role='owner').all()
        if lead_id is not None and not any(pc.property_id == lead_id for pc in links):
            continue
        if lead_id is not None:
            # Lead-scoped: only unlink THIS lead's shared generic link.
            for pc in links:
                if pc.property_id != lead_id:
                    continue
                unlinked.append({
                    'contact_id': cid,
                    'property_id': pc.property_id,
                    'name': display,
                    'was_linked_count': count,
                })
                if not dry_run:
                    db.session.delete(pc)
            continue
        # Keep the oldest link; unlink the rest so each property no longer shares.
        links_sorted = sorted(links, key=lambda pc: pc.id)
        for pc in links_sorted[1:]:
            unlinked.append({
                'contact_id': cid,
                'property_id': pc.property_id,
                'name': display,
                'was_linked_count': count,
            })
            if not dry_run:
                db.session.delete(pc)

    if not dry_run and unlinked:
        db.session.commit()

    return {
        'unlinked': len(unlinked),
        'rows': unlinked[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--lead-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--skip-mail', action='store_true')
    parser.add_argument('--skip-actions', action='store_true')
    parser.add_argument('--skip-addresses', action='store_true')
    parser.add_argument('--skip-dirty-streets', action='store_true')
    parser.add_argument('--skip-skip-trace-leaks', action='store_true')
    parser.add_argument('--skip-generic-owners', action='store_true')
    args = parser.parse_args()

    from app import create_app

    app = create_app()
    dry_run = bool(args.dry_run)
    with app.app_context():
        print('mode=%s' % ('apply' if args.apply else 'dry-run'))

        if not args.skip_addresses:
            addr = _heal_addresses(dry_run=dry_run, lead_id=args.lead_id, limit=args.limit)
            print(
                'addresses scanned=%s candidates=%s changed=%s'
                % (addr['scanned'], addr['candidates'], addr['changed'])
            )
            for row in addr['rows'][:25]:
                print('  lead=%s' % row['lead_id'])
                print('    before=%r' % row['before'])
                print('    after =%r' % row['after'])

        if not args.skip_dirty_streets:
            dirty = _heal_dirty_complete_streets(dry_run=dry_run, lead_id=args.lead_id)
            print(
                'dirty_streets scanned=%s changed=%s skipped_dup=%s'
                % (dirty['scanned'], dirty['changed'], dirty.get('skipped', 0))
            )
            for row in dirty['rows'][:25]:
                print('  lead=%s' % row['lead_id'])
                print('    before=%r' % row['before'])
                print('    after =%r' % row['after'])
            for row in dirty.get('skipped_rows', [])[:15]:
                print('  skip lead=%s %r (%s)' % (row['lead_id'], row['before'], row['reason']))

        if not args.skip_actions:
            acts = _heal_recommended_actions(
                dry_run=dry_run, lead_id=args.lead_id, limit=args.limit,
            )
            print('actions mismatches=%s' % acts['mismatches'])
            for row in acts['rows'][:25]:
                print('  %r' % row)

        if not args.skip_mail:
            mail = _recover_invalid_mail(dry_run=dry_run, lead_id=args.lead_id)
            print(
                'mail requeued=%s refreshed=%s still_invalid=%s'
                % (mail['requeued'], mail['refreshed_errors'], mail['still_invalid'])
            )
            for row in mail['requeued_rows'][:15]:
                print('  requeue %r' % row)

        if not args.skip_skip_trace_leaks:
            skip = _heal_skip_trace_todays_action_leaks(
                dry_run=dry_run, lead_id=args.lead_id,
            )
            print(
                'skip_trace_ta_leaks scanned=%s healed=%s'
                % (skip['scanned'], skip['healed'])
            )
            for row in skip['rows'][:25]:
                print('  %r' % row)

        if not args.skip_generic_owners:
            gen = _heal_generic_owner_contacts(dry_run=dry_run, lead_id=args.lead_id)
            print('generic_owner_unlinked=%s' % gen['unlinked'])
            for row in gen['rows'][:15]:
                print('  unlink %r' % row)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
