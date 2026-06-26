import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
url = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()
cur.execute("""
    SELECT pid FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid != pg_backend_pid()
      AND (
        state = 'idle in transaction'
        OR query ILIKE '%normalized_street%'
        OR query ILIKE '%merge_duplicate%'
        OR (query ILIKE '%ALTER TABLE leads%' AND state = 'active')
      )
""")
pids = [r[0] for r in cur.fetchall()]
for pid in pids:
    print(f'Terminating pid {pid}')
    cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
print(f'Terminated {len(pids)} session(s)')
cur.close()
conn.close()
