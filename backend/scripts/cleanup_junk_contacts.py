"""Delete obviously machine-generated ("junk") contact records.

Some leads accumulated synthetic contacts (e.g. property-test fuzz names like
``BOmjhdXntqoKgbsGCyPhUFZd``) that hold a stray copy of a phone/email. After the
flat->relational contact backfill (migration ``i3j4k5l6m7n8``) those values live
on the real primary owner contact, so the junk contacts are pure noise in the
Log Call / Log Email dropdowns.

This script finds junk contacts via the shared heuristic
``app.services.contact_backfill.looks_synthetic_name`` and -- only with
``--apply`` -- deletes them. Safety is decided by
``app.services.contact_backfill.preservation_gaps``: a junk contact is deleted
**only** when, for *every* property it links to, each of its phone/email values
is already held by another real (non-synthetic) contact of that *same* property
(checked per property, never as a global union). So every property keeps a usable
relational contact in the Log Call / Log Email dropdowns. Flat ``leads`` fields
are never counted (and never deleted). FK cascades remove the contact's phones,
emails, and property links.

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
    preservation_gaps,
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
            gaps = preservation_gaps(conn, contact_id)
            phones = gaps["phones"]
            emails = gaps["emails"]
            property_ids = gaps["property_ids"]
            safe = gaps["safe"]

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
                if gaps["orphan_with_methods"]:
                    logger.warning(
                        "    SKIP: orphan contact still holds %d phone(s)/%d email(s) "
                        "and links to no property",
                        len(phones),
                        len(emails),
                    )
                for pid, (lost_phones, lost_emails) in gaps["missing_by_property"].items():
                    if lost_phones:
                        logger.warning(
                            "    SKIP: property %s would lose %d phone(s) not on a real contact",
                            pid,
                            len(lost_phones),
                        )
                    if lost_emails:
                        logger.warning(
                            "    SKIP: property %s would lose %d email(s) not on a real contact",
                            pid,
                            len(lost_emails),
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
