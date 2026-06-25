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

This module is also the single home for the shared relational-contact helpers
used by ``scripts/cleanup_junk_contacts.py`` (``looks_synthetic_name``,
``phone_digits``, ``contact_methods``, ``preservation_gaps``) so that field
lists and merge/preservation logic are declared exactly once.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import sqlalchemy as sa

logger = logging.getLogger(__name__)

PHONE_COLUMNS = [f"phone_{i}" for i in range(1, 8)]
EMAIL_COLUMNS = [f"email_{i}" for i in range(1, 6)]

_SYNTHETIC_MIN_LEN = 15
_SYNTHETIC_MIN_INTERNAL_CAPS = 3

# A single contact method must fit its column: contact_phones.value is
# VARCHAR(50) and contact_emails.value is VARCHAR(255). Legacy flat
# phone_N / email_N fields occasionally hold a free-text dump of several values,
# so they are parsed into individual entries and anything that still won't fit
# is dropped (and counted) rather than allowed to abort the migration.
_MAX_PHONE_LEN = 50
_MAX_EMAIL_LEN = 255

# Matches a US-style 10-digit phone (optional +1 country code) with common
# separators, anywhere inside a larger string -- used to recover individual
# numbers from multi-number free-text fields such as
# "1) (773) 558-1863  2) (510) 685-0838 ...".
_PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")


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


def split_phone_field(raw) -> list:
    """Parse a legacy flat ``phone_N`` value into individual phone strings.

    Most fields hold a single number, but some are a free-text dump of several
    (e.g. ``"1) (773) 558-1863  2) (510) 685-0838 ..."``). Each US-style number
    is extracted so it can become its own ``ContactPhone``; when no pattern
    matches the whole trimmed value is used as a fallback (covers 7-digit and
    international numbers). Fragments without a plausible phone (7-15 digits) or
    longer than ``contact_phones.value`` allows are dropped, and the result is
    de-duped by digits. This keeps the backfill from ever inserting a value that
    would overflow the column.
    """
    if not raw:
        return []
    candidates = _PHONE_RE.findall(raw) or [raw.strip()]
    out: list = []
    seen: set = set()
    for candidate in (c.strip() for c in candidates):
        digits = phone_digits(candidate)
        if not (7 <= len(digits) <= 15):
            continue
        if len(candidate) > _MAX_PHONE_LEN:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        out.append(candidate)
    return out


def split_email_field(raw) -> list:
    """Parse a legacy flat ``email_N`` value into individual email strings.

    Splits on whitespace / commas / semicolons so a field holding several
    addresses yields one entry each. Tokens without an ``@`` or longer than
    ``contact_emails.value`` allows are dropped; the result is de-duped by
    lowercased value.
    """
    if not raw:
        return []
    out: list = []
    seen: set = set()
    for token in re.split(r"[\s,;]+", raw.strip()):
        token = token.strip().strip("<>")
        if "@" not in token or len(token) > _MAX_EMAIL_LEN:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def contact_methods(connection, contact_id):
    """Return a contact's ``(phone_digits_set, lowercased_email_set)``.

    The single normalized read of a contact's relational methods, shared by the
    backfill (dedup against what a target contact already has) and by
    ``scripts/cleanup_junk_contacts.py`` (preservation check) so neither
    re-declares the merge logic.
    """
    phones = {
        phone_digits(r._mapping["value"])
        for r in connection.execute(
            sa.text("SELECT value FROM contact_phones WHERE contact_id = :cid"),
            {"cid": contact_id},
        ).fetchall()
    }
    phones.discard("")
    emails = {
        (r._mapping["value"] or "").strip().lower()
        for r in connection.execute(
            sa.text("SELECT value FROM contact_emails WHERE contact_id = :cid"),
            {"cid": contact_id},
        ).fetchall()
    }
    emails.discard("")
    return phones, emails


def preservation_gaps(connection, contact_id) -> dict:
    """Per-property check of what deleting ``contact_id`` would orphan.

    Used by ``scripts/cleanup_junk_contacts.py`` to decide whether a junk contact
    is safe to delete. A contact is safe to delete only when, for *every* property
    it links to, all of its phones/emails are still held by some *other*
    non-synthetic contact of that property -- evaluated per property, never as a
    global union, so a contact linked to several properties is not deleted when
    even one property would lose its only relational copy of a value.

    Flat ``leads`` fields are intentionally NOT counted (they are never deleted),
    so the test is purely "does a real relational contact still carry this value".

    Returns a dict: ``property_ids``, ``phones``, ``emails``,
    ``missing_by_property`` (``{property_id: (lost_phones, lost_emails)}``),
    ``orphan_with_methods`` (has methods but links to no property), and a derived
    ``safe`` flag.
    """
    phones, emails = contact_methods(connection, contact_id)
    property_ids = [
        r._mapping["property_id"]
        for r in connection.execute(
            sa.text(
                "SELECT property_id FROM property_contacts WHERE contact_id = :cid"
            ),
            {"cid": contact_id},
        ).fetchall()
    ]

    missing_by_property: dict = {}
    for pid in property_ids:
        kept_phones: set[str] = set()
        kept_emails: set[str] = set()
        others = connection.execute(
            sa.text(
                """
                SELECT c.id AS contact_id, c.first_name AS first_name,
                       c.last_name AS last_name
                FROM property_contacts pc
                JOIN contacts c ON c.id = pc.contact_id
                WHERE pc.property_id = :pid AND c.id != :cid
                """
            ),
            {"pid": pid, "cid": contact_id},
        ).fetchall()
        for other in others:
            if looks_synthetic_name(
                other._mapping["first_name"], other._mapping["last_name"]
            ):
                continue
            other_phones, other_emails = contact_methods(
                connection, other._mapping["contact_id"]
            )
            kept_phones |= other_phones
            kept_emails |= other_emails
        lost_phones = phones - kept_phones
        lost_emails = emails - kept_emails
        if lost_phones or lost_emails:
            missing_by_property[pid] = (lost_phones, lost_emails)

    orphan_with_methods = not property_ids and bool(phones or emails)
    return {
        "property_ids": property_ids,
        "phones": phones,
        "emails": emails,
        "missing_by_property": missing_by_property,
        "orphan_with_methods": orphan_with_methods,
        "safe": not missing_by_property and not orphan_with_methods,
    }


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
        ``contacts_created``, ``phones_added``, ``emails_added``,
        ``phones_skipped_malformed``, ``emails_skipped_malformed`` (non-empty
        flat fields that yielded no storable value).
    """
    # contacts.created_at / updated_at are naive (db.DateTime); keep naive UTC
    # while avoiding the deprecated datetime.utcnow().
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stats = {
        "leads_processed": 0,
        "leads_skipped": 0,
        "contacts_created": 0,
        "phones_added": 0,
        "emails_added": 0,
        "phones_skipped_malformed": 0,
        "emails_skipped_malformed": 0,
    }

    select_cols = ", ".join(
        ["id", "owner_first_name", "owner_last_name"]
        + PHONE_COLUMNS
        + EMAIL_COLUMNS
    )
    flat_predicate = " OR ".join(
        f"coalesce({col}, '') <> ''" for col in PHONE_COLUMNS + EMAIL_COLUMNS
    )
    # select_cols / flat_predicate are built only from the module-level
    # PHONE_COLUMNS / EMAIL_COLUMNS constants (no user input), so this f-string
    # is not an injection vector.
    base_sql = f"SELECT {select_cols} FROM leads WHERE ({flat_predicate})"  # noqa: S608

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

        flat_phones: list = []
        for col in PHONE_COLUMNS:
            raw_phone = row[col]
            if not raw_phone or not raw_phone.strip():
                continue
            parsed = split_phone_field(raw_phone)
            if not parsed:
                # Non-empty but unusable (e.g. a blob whose digits don't form a
                # plausible phone). Count + log length only (avoid logging PII).
                stats["phones_skipped_malformed"] += 1
                logger.warning(
                    "lead %s %s: no usable phone extracted from flat field "
                    "(len=%d); skipped",
                    lead_id, col, len(raw_phone.strip()),
                )
                continue
            flat_phones.extend(parsed)

        flat_emails: list = []
        for col in EMAIL_COLUMNS:
            raw_email = row[col]
            if not raw_email or not raw_email.strip():
                continue
            parsed = split_email_field(raw_email)
            if not parsed:
                stats["emails_skipped_malformed"] += 1
                logger.warning(
                    "lead %s %s: no usable email extracted from flat field "
                    "(len=%d); skipped",
                    lead_id, col, len(raw_email.strip()),
                )
                continue
            flat_emails.extend(parsed)

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
            # existing_links is ordered is_primary-first, so non_synthetic[0] is
            # the real primary if one exists, else the first real contact.
            target = non_synthetic[0]
            target_contact_id = target._mapping["contact_id"]
            # Make the *real* contact the primary so the form defaults to it. A
            # synthetic junk contact may currently hold is_primary=True; counting
            # it in has_primary would leave the junk row as the default while the
            # repaired contact gets the data. Demote whatever is primary now and
            # promote the real target (mirrors the create branch below).
            if not target._mapping["is_primary"] and not dry_run:
                connection.execute(
                    sa.text(
                        "UPDATE property_contacts SET is_primary = :flag "
                        "WHERE property_id = :pid AND is_primary = :was"
                    ),
                    {"flag": False, "was": True, "pid": lead_id},
                )
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
            existing_phone_digits, existing_emails_lower = contact_methods(
                connection, target_contact_id
            )

        for phone in flat_phones:
            if len(phone) > _MAX_PHONE_LEN:
                # Defensive: split_phone_field already enforces this, so this
                # guards any future/other caller from overflowing the column.
                stats["phones_skipped_malformed"] += 1
                continue
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
            if len(email) > _MAX_EMAIL_LEN:
                # Defensive: split_email_field already enforces this.
                stats["emails_skipped_malformed"] += 1
                continue
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
        "phones_added=%d emails_added=%d leads_skipped=%d "
        "phones_skipped_malformed=%d emails_skipped_malformed=%d",
        "(dry-run)" if dry_run else "(applied)",
        stats["leads_processed"],
        stats["contacts_created"],
        stats["phones_added"],
        stats["emails_added"],
        stats["leads_skipped"],
        stats["phones_skipped_malformed"],
        stats["emails_skipped_malformed"],
    )
    return stats
