"""Delete obviously machine-generated ("junk") contact records.

Some leads accumulated synthetic contacts (e.g. property-test fuzz names like
``BOmjhdXntqoKgbsGCyPhUFZd``) that hold a stray copy of a phone/email. After the
flat->relational contact backfill (migration ``i3j4k5l6m7n8``) those values live
on the real primary owner contact, so the junk contacts are pure noise in the
Log Call / Log Email dropdowns.

This script finds junk contacts via the shared heuristic
``app.services.contact_backfill.looks_synthetic_name`` and -- only with
``--apply`` -- deletes them. A junk contact is deleted **only** when every one of
its phone/email values is already preserved elsewhere (on a linked lead's flat
fields or on a real contact of that lead), so nothing unique is ever lost. FK
cascades remove the contact's phones, emails, and property links.

Run AFTER the backfill migration, from the ``backend/`` directory:

    python scripts/cleanup_junk_contacts.py            # dry-run report (default)
    python scripts/cleanup_junk_contacts.py --apply    # actually delete
"""
import argparse
import logging
import os
import sys

import sqlalchemy as sa
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.contact_backfill import (  # noqa: E402
    looks_synthetic_name,
    phone_digits,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("cleanup_junk_contacts")


def _mask_phone(value) -> str:
    digits = phone_digits(value)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "<redacted>"


def _resolve_database_url(cli_value) -> str:
    if cli_value:
        return cli_value
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.error(
            "DATABASE_URL is not set. Set it in backend/.env or pass --database-url."
        )
        sys.exit(1)
    return url


def find_junk_contacts(conn):
    """Return [(contact_id, first_name, last_name), ...] for synthetic-named contacts."""
    rows = conn.execute(
        sa.text("SELECT id, first_name, last_name FROM contacts")
    ).fetchall()
    return [
        (r._mapping["id"], r._mapping["first_name"], r._mapping["last_name"])
        for r in rows
        if looks_synthetic_name(r._mapping["first_name"], r._mapping["last_name"])
    ]


def _contact_methods(conn, contact_id):
    phones = {
        phone_digits(r._mapping["value"])
        for r in conn.execute(
            sa.text("SELECT value FROM contact_phones WHERE contact_id = :cid"),
            {"cid": contact_id},
        ).fetchall()
    }
    phones.discard("")
    emails = {
        (r._mapping["value"] or "").strip().lower()
        for r in conn.execute(
            sa.text("SELECT value FROM contact_emails WHERE contact_id = :cid"),
            {"cid": contact_id},
        ).fetchall()
    }
    emails.discard("")
    return phones, emails


def _preserved_methods(conn, contact_id):
    """Phones/emails that survive a delete of ``contact_id``.

    Union, across every property the junk contact links to, of the phone/email
    values held by every *other* non-synthetic contact of that property.

    Flat ``leads`` fields are intentionally NOT counted: a junk contact is only
    safe to delete when a *real* relational contact already carries its data, so
    the property keeps a usable contact for the Log Call / Log Email dropdowns.
    (Flat fields are never deleted, so no data is lost either way.)
    """
    property_ids = [
        r._mapping["property_id"]
        for r in conn.execute(
            sa.text(
                "SELECT property_id FROM property_contacts WHERE contact_id = :cid"
            ),
            {"cid": contact_id},
        ).fetchall()
    ]

    preserved_phones: set[str] = set()
    preserved_emails: set[str] = set()
    for pid in property_ids:
        others = conn.execute(
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
            other_phones, other_emails = _contact_methods(
                conn, other._mapping["contact_id"]
            )
            preserved_phones |= other_phones
            preserved_emails |= other_emails

    return property_ids, preserved_phones, preserved_emails


def run(apply: bool, database_url) -> int:
    engine = sa.create_engine(_resolve_database_url(database_url))
    deletable: list[int] = []

    with engine.connect() as conn:
        junk = find_junk_contacts(conn)
        if not junk:
            logger.info("No junk contacts found. Nothing to do.")
            return 0

        logger.info("Found %d junk contact(s):", len(junk))
        for contact_id, first, last in junk:
            phones, emails = _contact_methods(conn, contact_id)
            property_ids, preserved_phones, preserved_emails = _preserved_methods(
                conn, contact_id
            )
            phones_safe = phones <= preserved_phones
            emails_safe = emails <= preserved_emails
            safe = phones_safe and emails_safe

            logger.info(
                "  contact id=%s name=%r linked_properties=%s phones=%s emails=%d safe=%s",
                contact_id,
                f"{first} {last}".strip(),
                property_ids or "(orphan)",
                sorted(_mask_phone(p) for p in phones) if phones else "[]",
                len(emails),
                safe,
            )
            if not safe:
                lost_phones = phones - preserved_phones
                if lost_phones:
                    logger.warning(
                        "    SKIP: %d phone(s) not preserved elsewhere", len(lost_phones)
                    )
                if emails - preserved_emails:
                    logger.warning(
                        "    SKIP: %d email(s) not preserved elsewhere",
                        len(emails - preserved_emails),
                    )
                continue
            deletable.append(contact_id)

    if not deletable:
        logger.info("No junk contacts are safe to delete.")
        return 0

    if not apply:
        logger.info(
            "DRY-RUN: would delete %d contact(s): %s. Re-run with --apply to delete.",
            len(deletable),
            deletable,
        )
        return 0

    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM contacts WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": deletable},
        )
    logger.info("Deleted %d junk contact(s): %s", len(deletable), deletable)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete safe junk contacts (default: dry-run report only).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the database URL (defaults to DATABASE_URL from backend/.env).",
    )
    args = parser.parse_args()
    sys.exit(run(apply=args.apply, database_url=args.database_url))


if __name__ == "__main__":
    main()
