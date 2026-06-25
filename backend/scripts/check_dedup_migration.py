import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
url = os.environ.get('DATABASE_URL', '').replace('postgresql+psycopg2://', 'postgresql://')
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute('SELECT version_num FROM alembic_version')
print('alembic:', cur.fetchone())
cur.execute(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name='leads' AND column_name='normalized_street'"
)
print('normalized_street column:', cur.fetchone())
cur.close()
conn.close()
