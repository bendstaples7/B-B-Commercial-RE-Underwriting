# backend/migrations — Historical Reference Only

> **⚠️ NON-AUTHORITATIVE: These files are NOT applied during deployment.**

## What these files are

The SQL files in this directory are historical records of the schema as it existed
before Alembic was introduced:

- `001_create_schema.sql`
- `002_lead_management.sql`
- `003_add_lead_category.sql`

They were applied manually to the original database, outside of any migration
management tool. They are kept here as a reference of how the schema evolved.

## What these files are NOT

- **Not part of the deployment path.** No deployment process, CI job, or migration
  command reads, applies, or depends on any file in this directory.
- **Not authoritative.** The schema defined here may be outdated, renamed, or
  superseded. Do not use these files to understand the current database schema.
- **Not idempotent.** These files were written without `IF NOT EXISTS` guards and
  will fail if applied to a database that already contains these objects.

## The authoritative schema source

**`backend/alembic_migrations/`** is the single authoritative source of schema truth.

The Alembic chain in that directory produces the complete, current database schema
when applied to a fresh PostgreSQL database — with zero files from this directory
required.

## The only command needed to deploy the schema

```bash
flask db upgrade
```

That is the only schema step required for any deployment (new environment or
existing). No `psql` command, no manual SQL execution, and no file from this
directory is part of the process.

## Why these files still exist

They are retained as a historical audit trail showing the pre-Alembic schema
baseline. They document where the schema originated, not where it is now.
Do not delete them, but do not apply them.
