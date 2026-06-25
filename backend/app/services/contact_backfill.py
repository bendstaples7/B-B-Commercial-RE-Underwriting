"""Backfill relational contacts from a lead's legacy flat fields.

Canonical, single source of truth for repairing the relational contacts system
(``Contact`` / ``ContactPhone`` / ``ContactEmail`` / ``PropertyContact``) from
the legacy flat columns on ``leads`` (``phone_1..7`` / ``email_1..5`` and the
owner name fields).

Why this exists
---------------
The original flat->relational migration
(``k1l2m3n4o5p6_add_contact_model.py``) only created contacts for leads that had
*no* ``property_contacts`` row yet. Leads that were partially or wrongly migrated
(e.g. their phones landed on a junk contact, or their primary owner contact has
zero phones) were never repaired, so the Log Call / Log Email phone & email
dropdowns -- which read the relational data via
``GET /api/properties/:id/contacts`` -- show no options.

This helper repairs every such lead by attaching its flat phones/emails to the
primary owner contact (creating that contact if necessary).

Design notes
------------
- Operates through a SQLAlchemy Core ``Connection`` so it is safe to call from
  both an Alembic migration (``op.get_bind()``) and a standalone script
  (``engine.connect()``).
- Idempotent: phones are deduped by digits-only value, emails by ``lower()``.
  Re-running adds nothing.
- Dialect-aware (Postgres in production, SQLite in tests).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import sqlalchemy as sa

logger = logging.getLogger(__name__)

PHONE_COLUMNS = [f"phone_{i}" for i in range(1, 8)]
EMAIL_COLUMNS = [f"email_{i}" for i in range(1, 6)]

_SYNTHETIC_MIN_LEN = 15
_SYNTHETIC_MIN_INTERNAL_CAPS = 3


def looks_synthetic_name(first_name, last_name) -> bool:
    """Conservatively flag obviously machine-generated ("junk") contact names.

    Returns ``True`` only when a name token is a single alphabetic run of length
    >= 15 with >= 3 *internal* uppercase letters (random mixed-case fuzz such as
    ``BOmjhdXntqoKgbsGCyPhUFZd`` / ``WBozLJoAwjbcWOCLFBRT``).

    The internal-capitals signal is deliberate: long *real* surnames that lost
    their spaces during import (e.g. ``Bichnguyenfranzen``) are normally
    capitalized (caps only at the start), so they are NOT flagged. Using a vowel
    ratio instead would false-positive on those real names -- and since the
    backfill creates primary contacts from ``owner_last_name``, flagging them
    would route the backfill around real data and let cleanup delete real
    contacts.

    Shared by the backfill (to avoid writing onto a junk contact) and by
    ``scripts/cleanup_junk_contacts.py`` (to identify deletion candidates).
    """
    for token in (first_name, last_name):
        if not token:
            continue
        stripped = token.strip()
        if (
            len(stripped) >= _SYNTHETIC_MIN_LEN
            and stripped.isalpha()
            and " " not in stripped
        ):
            internal_caps = sum(1 for ch in stripped[1:] if ch.isupper())
            if internal_caps >= _SYNTHETIC_MIN_INTERNAL_CAPS:
                return True
    return False


def phone_digits(value) -> str:
    """Digits-only normalization for phone dedup.

    Mirrors ``HubSpotMatcherService.normalize_phone`` /
    ``SearchService._digits_only``; kept dependency-free here so this module is
    safe to import from migration code.
    """
    return re.sub(r"\D", "", value or "")


def _insert_returning_id(connection, insert_sql: str, params: dict) -> int:
    """Run an INSERT and return the new row id, portably across dialects."""
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text(insert_sql), params)
        return connection.execute(sa.text("SELECT last_insert_rowid()")).scalar()
    return connection.execute(
        sa.text(insert_sql + " RETURNING id"), params
    ).scalar()


def backfill_contacts_from_flat_fields(
    connection, *, lead_ids=None, dry_run: bool = False
) -> dict:
    """Ensure each lead's primary owner ``Contact`` carries its flat methods.

    For every lead that has any non-empty ``phone_1..7`` / ``email_1..5``:

      1. Resolve the target owner contact -- an existing, non-synthetic
         ``property_contacts`` row (primary first); otherwise create one from
         the lead's ``owner_first_name`` / ``owner_last_name`` and link it as the
         primary owner.
      2. Insert each flat phone (``label='other'``) deduped by digits, and each
         flat email (``label='other'``) deduped by ``lower(value)``.

    Args:
        connection: a SQLAlchemy Core ``Connection`` (``op.get_bind()`` in a
            migration, or ``engine.connect()`` in a script/test).
        lead_ids: optional iterable restricting the run to specific lead ids.
        dry_run: when ``True``, compute and return counts without writing.

    Returns:
        A stats dict: ``leads_processed``, ``leads_skipped``,
        ``contacts_created``, ``phones_added``, ``emails_added``.
    """
    now = datetime.utcnow()
    stats = {
        "leads_processed": 0,
        "leads_skipped": 0,
        "contacts_created": 0,
        "phones_added": 0,
        "emails_added": 0,
    }

    select_cols = ", ".join(
        ["id", "owner_first_name", "owner_last_name"]
        + PHONE_COLUMNS
        + EMAIL_COLUMNS
    )
    flat_predicate = " OR ".join(
        f"coalesce({col}, '') <> ''" for col in PHONE_COLUMNS + EMAIL_COLUMNS
    )
    base_sql = f"SELECT {select_cols} FROM leads WHERE ({flat_predicate})"

    params: dict = {}
    if lead_ids is not None:
        ids = list(lead_ids)
        if not ids:
            return stats
        stmt = sa.text(base_sql + " AND id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        )
        params["ids"] = ids
    else:
        stmt = sa.text(base_sql)

    leads = connection.execute(stmt, params).fetchall()

    for lead in leads:
        row = lead._mapping
        lead_id = row["id"]
        owner_first = row["owner_first_name"]
        owner_last = row["owner_last_name"]

        flat_phones = [row[c].strip() for c in PHONE_COLUMNS if row[c] and row[c].strip()]
        flat_emails = [row[c].strip() for c in EMAIL_COLUMNS if row[c] and row[c].strip()]
        if not flat_phones and not flat_emails:
            continue

        existing_links = connection.execute(
            sa.text(
                """
                SELECT pc.id AS pc_id, pc.is_primary AS is_primary,
                       c.id AS contact_id, c.first_name AS first_name,
                       c.last_name AS last_name
                FROM property_contacts pc
                JOIN contacts c ON c.id = pc.contact_id
                WHERE pc.property_id = :pid
                ORDER BY pc.is_primary DESC, pc.id ASC
                """
            ),
            {"pid": lead_id},
        ).fetchall()

        non_synthetic = [
            link
            for link in existing_links
            if not looks_synthetic_name(
                link._mapping["first_name"], link._mapping["last_name"]
            )
        ]
        has_primary = any(link._mapping["is_primary"] for link in existing_links)

        target_contact_id = None
        if non_synthetic:
            target = non_synthetic[0]
            target_contact_id = target._mapping["contact_id"]
            # Guarantee a primary exists so the form's default selection works.
            if not has_primary and not dry_run:
                connection.execute(
                    sa.text(
                        "UPDATE property_contacts SET is_primary = :flag "
                        "WHERE id = :pcid"
                    ),
                    {"flag": True, "pcid": target._mapping["pc_id"]},
                )
        elif owner_first or owner_last:
            # No usable contact (none exist, or all are synthetic junk) -> create
            # a real owner contact and make it the primary.
            stats["contacts_created"] += 1
            if not dry_run:
                if has_primary:
                    connection.execute(
                        sa.text(
                            "UPDATE property_contacts SET is_primary = :flag "
                            "WHERE property_id = :pid AND is_primary = :was"
                        ),
                        {"flag": False, "was": True, "pid": lead_id},
                    )
                target_contact_id = _insert_returning_id(
                    connection,
                    """
                    INSERT INTO contacts (first_name, last_name, role, created_at, updated_at)
                    VALUES (:first_name, :last_name, 'owner', :created_at, :updated_at)
                    """,
                    {
                        "first_name": owner_first,
                        "last_name": owner_last,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
                        VALUES (:pid, :cid, 'owner', :flag)
                        """
                    ),
                    {"pid": lead_id, "cid": target_contact_id, "flag": True},
                )
        else:
            # Flat methods exist but there's no contact and no owner name to make
            # one from -- leave for manual review rather than create a nameless
            # contact.
            stats["leads_skipped"] += 1
            continue

        stats["leads_processed"] += 1

        existing_phone_digits: set[str] = set()
        existing_emails_lower: set[str] = set()
        if target_contact_id is not None:
            for prow in connection.execute(
                sa.text("SELECT value FROM contact_phones WHERE contact_id = :cid"),
                {"cid": target_contact_id},
            ).fetchall():
                existing_phone_digits.add(phone_digits(prow._mapping["value"]))
            for erow in connection.execute(
                sa.text("SELECT value FROM contact_emails WHERE contact_id = :cid"),
                {"cid": target_contact_id},
            ).fetchall():
                existing_emails_lower.add((erow._mapping["value"] or "").strip().lower())

        for phone in flat_phones:
            digits = phone_digits(phone)
            if not digits or digits in existing_phone_digits:
                continue
            existing_phone_digits.add(digits)
            stats["phones_added"] += 1
            if not dry_run:
                connection.execute(
                    sa.text(
                        "INSERT INTO contact_phones (contact_id, value, label) "
                        "VALUES (:cid, :value, 'other')"
                    ),
                    {"cid": target_contact_id, "value": phone},
                )

        for email in flat_emails:
            key = email.lower()
            if key in existing_emails_lower:
                continue
            existing_emails_lower.add(key)
            stats["emails_added"] += 1
            if not dry_run:
                connection.execute(
                    sa.text(
                        "INSERT INTO contact_emails (contact_id, value, label) "
                        "VALUES (:cid, :value, 'other')"
                    ),
                    {"cid": target_contact_id, "value": email},
                )

    logger.info(
        "contact backfill %s: leads_processed=%d contacts_created=%d "
        "phones_added=%d emails_added=%d leads_skipped=%d",
        "(dry-run)" if dry_run else "(applied)",
        stats["leads_processed"],
        stats["contacts_created"],
        stats["phones_added"],
        stats["emails_added"],
        stats["leads_skipped"],
    )
    return stats
