"""Diagnose Ronald Jutkins HubSpot sync status."""
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
url = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
conn = psycopg2.connect(url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT id, property_street, lead_status, hubspot_deal_stage,
           last_hubspot_sync_at, owner_first_name, owner_last_name
    FROM leads
    WHERE owner_last_name ILIKE 'Jutkins' AND owner_first_name ILIKE 'Ronald%'
""")
leads = cur.fetchall()
print('=== LEADS ===')
for l in leads:
    print(dict(l))

if leads:
    lid = leads[0]['id']
    cur.execute("""
        SELECT id, hubspot_id, hubspot_record_type, status, confidence,
               matching_criteria, internal_record_id, updated_at
        FROM hubspot_matches
        WHERE internal_record_type = 'lead' AND internal_record_id = %s
    """, (lid,))
    print('\n=== HUBSPOT MATCHES ===')
    for m in cur.fetchall():
        print(dict(m))

    cur.execute("""
        SELECT hd.hubspot_id,
               hd.raw_payload->'properties'->>'dealname' AS dealname,
               hd.raw_payload->'properties'->>'dealstage' AS dealstage_id,
               hd.last_updated_at
        FROM hubspot_deals hd
        JOIN hubspot_matches hm ON hm.hubspot_id = hd.hubspot_id
            AND hm.hubspot_record_type = 'deal'
        WHERE hm.internal_record_id = %s
    """, (lid,))
    print('\n=== LINKED HUBSPOT DEALS ===')
    deals = cur.fetchall()
    for d in deals:
        row = dict(d)
        print(row)
        cur.execute(
            "SELECT id, event_type, processed, created_at FROM hubspot_webhook_events "
            "WHERE object_id = %s ORDER BY created_at DESC LIMIT 5",
            (row['hubspot_id'],),
        )
        wh = cur.fetchall()
        if wh:
            print('  recent webhooks:', [dict(w) for w in wh])

cur.execute("""
    SELECT id, hubspot_id,
           raw_payload->'properties'->>'dealname' AS dealname,
           raw_payload->'properties'->>'dealstage' AS dealstage_prop,
           last_updated_at
    FROM hubspot_deals
    WHERE hubspot_id = '52218559108'
       OR raw_payload->'properties'->>'dealname' ILIKE '%Jutkins%'
       OR raw_payload->'properties'->>'dealname' ILIKE '%Schiller%'
    ORDER BY last_updated_at DESC LIMIT 5
""")
print('\n=== DEALS BY NAME ===')
for d in cur.fetchall():
    print(dict(d))

cur.execute("""
    SELECT id, event_type, hubspot_object_type, hubspot_object_id, status,
           received_at, processed_at, error_message
    FROM hubspot_webhook_logs
    WHERE hubspot_object_id = '52218559108'
    ORDER BY received_at DESC LIMIT 10
""")
print('\n=== WEBHOOK LOGS FOR DEAL ===')
for w in cur.fetchall():
    print(dict(w))

cur.close()
conn.close()
