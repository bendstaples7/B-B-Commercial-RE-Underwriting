# Migration Conventions

## Rule: All new migrations must be idempotent

Every migration must be safe to run more than once without failing. This prevents
the "partial migration" failure mode where a migration runs halfway, leaves the DB
in an inconsistent state, and then can't be re-run because objects already exist.

## How to write idempotent migrations

### Adding columns — use raw SQL with IF NOT EXISTS

```python
def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS lead_status VARCHAR(50) NOT NULL DEFAULT 'new'
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS review_required BOOLEAN NOT NULL DEFAULT FALSE
    """)
```

Never use `batch_alter_table` for PostgreSQL — it's designed for SQLite and
creates a new table + copy + drop, which fails if enum types already exist.

### Creating tables — use IF NOT EXISTS

```python
def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS lead_tasks (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'open',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
```

### Creating enum types — use IF NOT EXISTS

```python
def upgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE lead_status_enum AS ENUM ('new', 'active', 'follow_up');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
```

### Creating indexes — use IF NOT EXISTS

```python
def upgrade():
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_lead_status ON leads(lead_status)
    """)
```

## Why not SQLAlchemy DDL helpers?

`op.add_column()`, `op.create_table()`, and `op.create_index()` do NOT support
`IF NOT EXISTS` natively. They fail with `DuplicateObject` if the object already
exists — which happens when:
- A migration was partially applied and the Alembic version table wasn't updated
- The same migration runs on two environments at slightly different times
- A developer manually created a column/table to test something

Raw `op.execute()` with `IF NOT EXISTS` avoids all of these.

## Downgrade functions

Always implement `downgrade()` using the corresponding `DROP ... IF EXISTS`:

```python
def downgrade():
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lead_status")
    op.execute("DROP INDEX IF EXISTS ix_leads_lead_status")
    op.execute("DROP TYPE IF EXISTS lead_status_enum")
```

## Existing migrations

Do NOT rewrite existing migration files. The idempotent pattern applies to all
new migrations created after this convention was established. Existing migrations
are already applied to production and rewriting them would break the migration chain.
