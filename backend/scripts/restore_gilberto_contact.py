"""One-time script: restore the missing contact for Gilberto Olivares (lead id=3415).

The merge script's UniqueViolation handler deleted the property_contacts row
for lead 3415 during the duplicate merge. The contacts row was subsequently
cascade-deleted. Phone data survives in the flat lead fields.

This script:
1. Creates a new Contact row for Gilberto Olivares
2. Inserts contact_phones rows for his three phone numbers
3. Links the contact to lead 3415 via property_contacts (role=owner, is_primary=True)

Safe to re-run — checks for existing contact before inserting.
"""
import os
import sys
import psycopg2
import psycopg2.extras
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

LEAD_ID = 3415
FIRST_NAME = 'Gilberto'
LAST_NAME = 'Olivares'
PHONES = [
    ('(630) 202-3839', 'mobile'),
    ('(630) 430-5720', 'mobile'),
    ('(630) 783-8622', 'mobile'),
]


def run():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)
    dsn = db_url.replace('postgresql+psycopg2://', 'postgresql://')
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 1. Check whether the SPECIFIC target contact (Gilberto Olivares) is
        #    already linked to this lead. The contact is identified by name
        #    (FIRST_NAME / LAST_NAME) since this restore has no email. A different
        #    contact being linked must NOT cause us to skip — otherwise Gilberto
        #    himself can stay missing while some other contact occupies the lead.
        cur.execute(
            """SELECT pc.id
               FROM property_contacts pc
               JOIN contacts c ON c.id = pc.contact_id
               WHERE pc.property_id = %s
                 AND lower(c.first_name) = lower(%s)
                 AND lower(c.last_name) = lower(%s)
               LIMIT 1""",
            (LEAD_ID, FIRST_NAME, LAST_NAME),
        )
        if cur.fetchone():
            logger.info(
                "Lead %d already has the %s %s contact linked — nothing to do.",
                LEAD_ID, FIRST_NAME, LAST_NAME,
            )
            return

        # 2. Create the contact (role is NOT NULL, default 'owner')
        cur.execute(
            """INSERT INTO contacts (first_name, last_name, role, created_at, updated_at)
               VALUES (%s, %s, 'owner', NOW(), NOW()) RETURNING id""",
            (FIRST_NAME, LAST_NAME),
        )
        contact_id = cur.fetchone()['id']
        logger.info("Created contact id=%d (%s %s)", contact_id, FIRST_NAME, LAST_NAME)

        # 3. Insert phone numbers (label enum: mobile/home/work/other; no created_at/updated_at)
        for phone_value, phone_label in PHONES:
            cur.execute(
                "INSERT INTO contact_phones (contact_id, value, label) VALUES (%s, %s, %s)",
                (contact_id, phone_value, phone_label),
            )
            logger.info("  Added phone %s (%s)", phone_value, phone_label)

        # 4. Link contact to lead
        cur.execute(
            """INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
               VALUES (%s, %s, 'owner', TRUE)""",
            (LEAD_ID, contact_id),
        )
        logger.info("Linked contact %d to lead %d as primary owner", contact_id, LEAD_ID)

        conn.commit()
        logger.info("Done.")

    except Exception as exc:
        conn.rollback()
        logger.error("Failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    run()
