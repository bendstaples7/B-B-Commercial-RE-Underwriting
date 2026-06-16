"""One-time script: restore missing Contact records for all winner leads from
the duplicate merge (merge_duplicate_leads.py) where the merge script's
UniqueViolation handler cascade-deleted the contact data.

Affected leads (winner IDs with flat phone/email data but no contact link):
  460  - Michael Noonan       (2 phones, 1 email)
  3349 - Agustin Flores       (3 phones)
  3362 - Krystyna Tchorz      (3 phones)
  3415 - Gilberto Olivares    (3 phones) — already fixed, script skips if linked
  3905 - Lydia Cardelli       (2 phones, 1 email)
  4037 - Gary Carlson         (1 phone)

For each affected lead:
1. Check if a contact is already linked (idempotent — skip if yes)
2. Create a Contact row from lead's owner_first_name / owner_last_name
3. Insert contact_phones from phone_1 / phone_2 / phone_3
4. Insert contact_emails from email_1 / email_2
5. Link via property_contacts (role=owner, is_primary=True)

Run from the backend/ directory on the VPS:
    DATABASE_URL='...' python3.11 scripts/restore_merged_contacts.py
"""
import os
import sys
import psycopg2
import psycopg2.extras
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Winner lead IDs that need contacts restored.
# Determined by: no property_contacts row AND flat phone/email fields populated.
AFFECTED_LEAD_IDS = [460, 3349, 3362, 3415, 3905, 4037]


def restore_contact_for_lead(cur, lead):
    lead_id = lead['id']

    # Already has a contact linked — skip
    cur.execute(
        "SELECT id FROM property_contacts WHERE property_id = %s LIMIT 1",
        (lead_id,)
    )
    if cur.fetchone():
        logger.info("Lead %d (%s %s) already has contact — skipping",
                    lead_id, lead['owner_first_name'], lead['owner_last_name'])
        return

    # Create contact
    cur.execute(
        """INSERT INTO contacts (first_name, last_name, role, created_at, updated_at)
           VALUES (%s, %s, 'owner', NOW(), NOW()) RETURNING id""",
        (lead['owner_first_name'], lead['owner_last_name']),
    )
    contact_id = cur.fetchone()['id']
    logger.info("Lead %d: created contact id=%d (%s %s)",
                lead_id, contact_id, lead['owner_first_name'], lead['owner_last_name'])

    # Insert phones
    for col in ('phone_1', 'phone_2', 'phone_3'):
        val = lead.get(col)
        if val:
            cur.execute(
                "INSERT INTO contact_phones (contact_id, value, label) VALUES (%s, %s, 'mobile')",
                (contact_id, val),
            )
            logger.info("  Added phone %s", val)

    # Insert emails
    for col in ('email_1', 'email_2'):
        val = lead.get(col)
        if val:
            cur.execute(
                "INSERT INTO contact_emails (contact_id, value, label) VALUES (%s, %s, 'personal')",
                (contact_id, val),
            )
            logger.info("  Added email %s", val)

    # Link to lead
    cur.execute(
        """INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
           VALUES (%s, %s, 'owner', TRUE)""",
        (lead_id, contact_id),
    )
    logger.info("  Linked contact %d to lead %d", contact_id, lead_id)


def run():
    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://app_user:BBanalyzer2025!@localhost:5432/real_estate_analysis',
    )
    dsn = db_url.replace('postgresql+psycopg2://', 'postgresql://')
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        placeholders = ','.join(['%s'] * len(AFFECTED_LEAD_IDS))
        cur.execute(
            f"SELECT id, owner_first_name, owner_last_name, phone_1, phone_2, phone_3, email_1, email_2 "
            f"FROM leads WHERE id IN ({placeholders}) ORDER BY id",
            AFFECTED_LEAD_IDS,
        )
        leads = cur.fetchall()

        for lead in leads:
            restore_contact_for_lead(cur, lead)

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
