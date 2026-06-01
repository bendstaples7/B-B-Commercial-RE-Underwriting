#!/usr/bin/env python3
"""
inject-db-creds.py — Inject PostgreSQL credentials from DATABASE_URL into backup.conf.

Called by the deploy workflow after setup-stub-conf.py to ensure backup.sh
uses the correct DB user, host, and password from the GitHub secret DATABASE_URL.
This eliminates the class of failures caused by wrong PGUSER in the stub.

Reads DATABASE_URL from the environment variable set by the deploy workflow.
"""
import os
import re
from urllib.parse import urlparse

CONF = "/home/deploy/backup.conf"
PGPASS = "/home/deploy/.pgpass"

db_url = os.environ.get("DATABASE_URL", "")
if not db_url:
    print("WARNING: DATABASE_URL not set — skipping credential injection")
    raise SystemExit(0)

parsed = urlparse(db_url)
if not parsed.username or not parsed.hostname:
    print("WARNING: Could not parse DATABASE_URL format — skipping injection")
    raise SystemExit(0)

user = parsed.username
password = parsed.password or ""
host = parsed.hostname
try:
    port = str(parsed.port) if parsed.port is not None else "5432"
except ValueError:
    print("WARNING: DATABASE_URL has an invalid port — using default 5432")
    port = "5432"
dbname = parsed.path.lstrip("/")

if not dbname:
    print("WARNING: DATABASE_URL has no database name — skipping injection")
    raise SystemExit(0)

print(f"Injecting credentials: PGUSER={user} PGHOST={host} PGDATABASE={dbname}")

# Update backup.conf
with open(CONF) as f:
    conf = f.read()


def set_var(conf, name, value):
    pattern = rf"^{name}=.*"
    replacement = f'{name}="{value}"'
    if re.search(pattern, conf, flags=re.MULTILINE):
        return re.sub(pattern, replacement, conf, flags=re.MULTILINE)
    else:
        return conf + f'{name}="{value}"\n'


conf = set_var(conf, "PGUSER", user)
conf = set_var(conf, "PGHOST", host)
conf = set_var(conf, "PGDATABASE", dbname)
# Store password separately in .pgpass — never in backup.conf
# Remove any PGPASSWORD from backup.conf if present
conf = re.sub(r"^PGPASSWORD=.*\n?", "", conf, flags=re.MULTILINE)

with open(CONF, "w") as f:
    f.write(conf)
os.chmod(CONF, 0o600)
print("backup.conf updated")

# Write .pgpass for pg_dump TCP auth
pgpass_line = f"{host}:{port}:{dbname}:{user}:{password}"
with open(PGPASS, "w") as f:
    f.write(pgpass_line + "\n")
os.chmod(PGPASS, 0o600)
print(".pgpass updated")
