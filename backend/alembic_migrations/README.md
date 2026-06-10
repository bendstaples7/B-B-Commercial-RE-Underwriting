# Alembic Migrations — Single Authoritative Schema Source

`backend/alembic_migrations/` is the **single authoritative source** of database schema truth
for this application.  Every table, column, index, constraint, and enum type required by the
application's SQLAlchemy models is produced by applying the revision chain in this directory
to an empty PostgreSQL database — with **zero** manual SQL steps and **zero** dependency on
the raw SQL files in `backend/migrations/`.

> **`backend/migrations/` contains non-authoritative historical reference files only.**
> The files `001_create_schema.sql`, `002_lead_management.sql`, and `003_add_lead_category.sql`
> are retained for historical record but are **not** applied during deployment.  No deployment
> or migration command reads, applies, or depends on any file in `backend/migrations/`.
> See [`backend/migrations/README.md`](../migrations/README.md) for the formal notice.

---

## Deploying the schema

The only schema step required to deploy is:

```bash
flask db upgrade
```

Do **not** run `psql`, do **not** apply raw SQL files, do **not** execute any manual SQL
statement.  `flask db upgrade` is the complete and only deployment step.

---

## Baseline-Replacement Mapping

The clean-baseline (squash) strategy adds new revision files without modifying any revision
already applied to production.  The table below documents every revision in the chain, which
consolidated baseline revision covers it, and the pre-consolidation revisions that each
baseline subsumes.

### Consolidated baseline revisions

| Baseline revision ID | Description | Replaces (pre-consolidation revisions) |
|---|---|---|
| `000000000000` | `initial_schema` — single root; creates all pre-Alembic tables, the `users` table, indexes, and enum types using idempotent raw SQL (`CREATE TABLE IF NOT EXISTS`, `EXCEPTION WHEN duplicate_object`, `CREATE INDEX IF NOT EXISTS`). | Is itself the baseline root; not replaced by any prior revision. |
| `267725fe7017` | `baseline_schema` — neutralised for fresh-DB safety; idempotent no-op when target types already match model-aligned form. | Covered by `000000000000` (its direct predecessor). |
| `b3c4d5e6f7a1` | `squash_marker` — single unambiguous Migration_Head; thin/empty `upgrade()`/`downgrade()`. Subsumes the entire pre-consolidation chain. | All revisions from `a1b2c3d4e5f6` through `z5a6b7c8d9e0` (see full table below). |

### Full revision mapping table

Every revision from `000000000000` through `b3c4d5e6f7a1` is listed below.  No pre-consolidation
revision is left unmapped.

| Revision ID | Description | Covered by baseline |
|---|---|---|
| `000000000000` | `initial_schema` (baseline root) | Self — is a baseline revision |
| `267725fe7017` | `baseline_schema` (now fresh-DB-safe) | `267725fe7017` — is a baseline revision |
| `a1b2c3d4e5f6` | `add_condo_filter_schema` | `b3c4d5e6f7a1` (squash_marker) |
| `b2c3d4e5f6g7` | `add_lead_scores_table` | `b3c4d5e6f7a1` (squash_marker) |
| `c3d4e5f6g7h8` | `multifamily_schema` | `b3c4d5e6f7a1` (squash_marker) |
| `d4e5f6g7h8i9` | `commercial_om_intake_schema` / `add_min_comparables` | `b3c4d5e6f7a1` (squash_marker) |
| `d4e5f6g7h8i9b` | `add_min_comparables_to_scoring_weights` | `b3c4d5e6f7a1` (squash_marker) |
| `e5f6g7h8i9j0` | `merge_heads` | `b3c4d5e6f7a1` (squash_marker) |
| `e5f6g7h8i9j0b` | `add_completed_steps_and_step_results` | `b3c4d5e6f7a1` (squash_marker) |
| `f6g7h8i9j0k1` | `add_confidence_score` / `rentcast_cache` | `b3c4d5e6f7a1` (squash_marker) |
| `f6g7h8i9j0k1b` | `rentcast_cache` | `b3c4d5e6f7a1` (squash_marker) |
| `f6g7h8i9j0k1c` | `merge_confidence_and_rentcast` | `b3c4d5e6f7a1` (squash_marker) |
| `fd5451087f07` | `add_loading_column_to_analysis_session` | `b3c4d5e6f7a1` (squash_marker) |
| `g7h8i9j0k1l2` | `sale_comp_nullable_cap_rate` / `add_socrata_cache_tables` | `b3c4d5e6f7a1` (squash_marker) |
| `g7h8i9j0k1l2b` | `add_socrata_cache_tables` | `b3c4d5e6f7a1` (squash_marker) |
| `g7h8i9j0k1l2c` | `merge_sale_comp_and_socrata` | `b3c4d5e6f7a1` (squash_marker) |
| `h8i9j0k1l2m3` | `add_hubspot_crm_tables` | `b3c4d5e6f7a1` (squash_marker) |
| `i9j0k1l2m3n4` | `add_lead_suppression_and_recommended_action` | `b3c4d5e6f7a1` (squash_marker) |
| `j0k1l2m3n4o5` | `seed_hubspot_signal_dictionary` | `b3c4d5e6f7a1` (squash_marker) |
| `k1l2m3n4o5p6` | `add_contact_model` | `b3c4d5e6f7a1` (squash_marker) |
| `l2m3n4o5p6q7` | `contact_email_lower_index` | `b3c4d5e6f7a1` (squash_marker) |
| `m3n4o5p6q7r8` | `add_crm_columns_to_leads` | `b3c4d5e6f7a1` (squash_marker) |
| `n4o5p6q7r8s9` | `create_lead_tasks_table` | `b3c4d5e6f7a1` (squash_marker) |
| `o5p6q7r8s9t0` | `create_lead_timeline_entries_table` | `b3c4d5e6f7a1` (squash_marker) |
| `p6q7r8s9t0u1` | `add_lead_id_to_tasks` | `b3c4d5e6f7a1` (squash_marker) |
| `q7r8s9t0u1v2` | `create_lead_crm_flags_view` | `b3c4d5e6f7a1` (squash_marker) |
| `r8s9t0u1v2w3` | `add_hubspot_webhook_tables` | `b3c4d5e6f7a1` (squash_marker) |
| `r9s0t1u2v3w4` | `backfill_lead_enrichment_from_hubspot` | `b3c4d5e6f7a1` (squash_marker) |
| `s0t1u2v3w4x5` | `expand_lead_status_to_pipeline_stages` | `b3c4d5e6f7a1` (squash_marker) |
| `t0u1v2w3x4y5` | `add_is_admin_to_users` | `b3c4d5e6f7a1` (squash_marker) |
| `u1v2w3x4y5z6` | `add_suggested_comps_columns` | `b3c4d5e6f7a1` (squash_marker) |
| `v1w2x3y4z5a6` | `add_owner_user_id_to_leads` | `b3c4d5e6f7a1` (squash_marker) |
| `w2x3y4z5a6b7` | `seed_sub_users_and_reassign_leads` | `b3c4d5e6f7a1` (squash_marker) |
| `x3y4z5a6b7c8` | `add_dupage_lead_columns` | `b3c4d5e6f7a1` (squash_marker) |
| `y4z5a6b7c8d9` | `add_import_job_source_type` | `b3c4d5e6f7a1` (squash_marker) |
| `z5a6b7c8d9e0` | `drop_leads_property_street_unique` (pre-consolidation chain end) | `b3c4d5e6f7a1` (squash_marker) |
| `a2b3c4d5e6f7` | `model_alignment` (new consolidation revision) | `b3c4d5e6f7a1` (squash_marker) |
| `b3c4d5e6f7a1` | `squash_marker` (new head) | Self — is the Migration_Head |

---

## Stamp path for existing production databases

Production databases whose recorded revision is any revision in the pre-consolidation chain
(`000000000000` through `z5a6b7c8d9e0`) should be advanced to the new head by running the
normal upgrade command:

```bash
flask db upgrade
```

If the database was already stamped to a baseline revision manually and you need to advance
the recorded revision **without** applying schema changes, use the stamp command:

```bash
flask db stamp b3c4d5e6f7a1
```

**IMPORTANT:** The assumed starting revision for the stamp command is any revision in the
pre-consolidation chain (`000000000000` through `z5a6b7c8d9e0`).

**Stamping changes ONLY the recorded revision in the `alembic_version` table and applies NO
schema changes.**  Only use `stamp` when you are certain the database schema already reflects
all migrations up to and including revision `b3c4d5e6f7a1`.  If in doubt, use
`flask db upgrade` instead — it is idempotent and will apply only the changes that are missing.

---

## Unrecognized-starting-revision halt behavior

If the upgrade path is executed against a database whose recorded revision is **not** in the
known revisions set listed below, the upgrade guard will halt before applying any schema change
and will emit an error identifying the unrecognized starting revision.  The database schema and
recorded revision will remain unchanged.

### Known revision IDs recognized by the upgrade guard

```
000000000000
267725fe7017
a1b2c3d4e5f6
b2c3d4e5f6g7
c3d4e5f6g7h8
d4e5f6g7h8i9
d4e5f6g7h8i9b
e5f6g7h8i9j0
e5f6g7h8i9j0b
f6g7h8i9j0k1
f6g7h8i9j0k1b
f6g7h8i9j0k1c
fd5451087f07
g7h8i9j0k1l2
g7h8i9j0k1l2b
g7h8i9j0k1l2c
h8i9j0k1l2m3
i9j0k1l2m3n4
j0k1l2m3n4o5
k1l2m3n4o5p6
l2m3n4o5p6q7
m3n4o5p6q7r8
n4o5p6q7r8s9
o5p6q7r8s9t0
p6q7r8s9t0u1
q7r8s9t0u1v2
r8s9t0u1v2w3
r9s0t1u2v3w4
s0t1u2v3w4x5
t0u1v2w3x4y5
u1v2w3x4y5z6
v1w2x3y4z5a6
w2x3y4z5a6b7
x3y4z5a6b7c8
y4z5a6b7c8d9
z5a6b7c8d9e0
a2b3c4d5e6f7
b3c4d5e6f7a1
```

Any revision not in this list is considered unrecognized.  The guard treats an unrecognized
starting revision as a sign that the database may belong to a different schema lineage or may
have been modified outside the documented migration path.  No schema changes are applied until
the starting revision is verified.

---

## Idempotency convention

All migrations in this directory follow the convention defined in
[`.kiro/steering/migrations.md`](../../.kiro/steering/migrations.md):

- Tables are created with `CREATE TABLE IF NOT EXISTS`
- Enum types are created inside `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$;` blocks
- Indexes are created with `CREATE INDEX IF NOT EXISTS`
- Columns are added with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- No `batch_alter_table` on PostgreSQL
- Every `upgrade()` has a corresponding `downgrade()` using `DROP ... IF EXISTS`

This means every migration is safe to run more than once and recoverable from partial application.
