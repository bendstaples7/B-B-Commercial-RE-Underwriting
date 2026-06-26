import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
url = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute("""
    SELECT pid, state, wait_event_type, wait_event,
           left(query, 80) AS query
    FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid != pg_backend_pid()
      AND state != 'idle'
    ORDER BY pid
""")
rows = cur.fetchall()
print('active queries:', len(rows))
for r in rows:
    print(r)
cur.execute('SELECT version_num FROM alembic_version')
print('alembic:', cur.fetchone())
cur.close()
conn.close()
