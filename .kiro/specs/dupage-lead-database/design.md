# Design Document: DuPage Lead Database

## Overview

This feature extends the platform's lead data model and scoring engine with new capabilities that apply to all leads in the system. DuPage County is the first market fully loaded using these capabilities.

### What changes
- **Database**: Three new columns (`source_type`, `tax_distress_data`, `manual_priority`) and two composite indexes on the `leads` table.
- **Lead Model**: SQLAlchemy `Property` model updated with the three new columns.
- **GIS Connector**: A pluggable `GISConnector` interface with `DuPageGISConnector` as the first concrete implementation.
- **Lead Ingestion Service**: New `LeadIngestionService` with per-source handlers and an improved `DeduplicationEngine`.
- **Scoring Engine**: New `source_type_distress` dimension in `DeterministicScoringEngine`; `manual_priority` already has a hook; `absentee_owner` short-circuits on `source_type`.
- **ImportJob model**: New `source_type` column to track which source type a job ingested.
- **REST API**: Five new ingestion endpoints + one updated CSV upload endpoint, plus extended `GET /api/leads/` filters.
- **Frontend**: `source_type` and `owner_user_id` filter controls added to the existing lead list UI.

### Design principles
- **Platform-first**: Every new column, scoring dimension, and API filter works for any lead in the system, not only DuPage County leads. DuPage is the first consumer, not a silo.
- **Idempotent migrations**: All DDL uses `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` per project convention.
- **Non-destructive deduplication**: Existing non-null field values are never overwritten by incoming data; conflicts are logged.
- **Tax distress privacy**: `tax_distress_data` is a scoring-only field. Its contents never propagate to `notes`, `top_signals`, or `recommended_action`.
- **Pluggable GIS**: The `GISConnector` abstract interface ensures future markets can add their own connectors without changing ingestion logic.

---

## Architecture

```
REST API Layer (Flask Blueprints)
  ├── ingestion_controller.py   ← new Blueprint: /api/ingestion/*
  └── lead_controller.py        ← extended: source_type + owner_user_id filters

Lead Ingestion Service
  ├── LeadIngestionService       ← orchestrates all source types
  │     ├── ForeclosureHandler
  │     ├── LongOwnedHandler
  │     ├── AbsenteeOwnerHandler
  │     ├── TaxDistressHandler
  │     └── ManualDistressHandler (CSV)
  ├── DeduplicationEngine        ← address + PIN matching, conflict logging
  └── GIS Connector Interface
        └── DuPageGISConnector   ← first implementation

Scoring Engine
  └── DeterministicScoringEngine (extended)
        └── source_type_distress dimension (new)

Database
  └── leads table (3 new columns, 2 new indexes)
```

### Async flow (CSV > 500 rows)

```
POST /api/ingestion/csv  (file > 500 rows)
  → validate file, create ImportJob (status=pending)
  → enqueue Celery task: process_csv_ingestion.delay(job_id, tmp_path)
  → return 202 { import_job_id }

Celery worker:
  → LeadIngestionService.process_csv(job_id, file_path)
  → ManualDistressHandler row-by-row
  → DeduplicationEngine per row
  → ImportJob status updates throughout
  → ImportJob status=completed|failed on finish
```

### Sync flow (CSV ≤ 500 rows)

```
POST /api/ingestion/csv  (file ≤ 500 rows)
  → validate file, create ImportJob
  → LeadIngestionService.process_csv() — runs inline in request
  → return 200 { summary }
```

---

## Components and Interfaces

### 1. GIS Connector Interface

**File**: `backend/app/services/gis/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class GISParcel:
    county_assessor_pin: Optional[str]
    property_type: Optional[str]
    year_built: Optional[int]
    square_footage: Optional[int]
    bedrooms: Optional[int]
    bathrooms: Optional[float]
    lot_size: Optional[int]
    owner_first_name: Optional[str]
    owner_last_name: Optional[str]
    mailing_address: Optional[str]
    mailing_city: Optional[str]
    mailing_state: Optional[str]
    mailing_zip: Optional[str]

class GISConnector(ABC):
    """Interface all GIS connectors must implement."""

    @abstractmethod
    def lookup_by_address(self, address: str) -> Optional[GISParcel]:
        """Lookup parcel by property address. Returns None if not found."""
        ...

    @abstractmethod
    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Lookup parcel by PIN. Returns None if not found."""
        ...

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Machine-readable connector identifier, e.g. 'dupage_gis'."""
        ...

    @property
    @abstractmethod
    def market(self) -> str:
        """Market identifier this connector serves, e.g. 'dupage_il'."""
        ...
```

### 2. DuPage GIS Connector

**File**: `backend/app/services/gis/dupage_gis_connector.py`

```python
class DuPageGISConnector(GISConnector):
    """Concrete GIS connector for DuPage County, IL parcel dataset.

    Calls the DuPage County GIS REST endpoint (or a configured mock URL)
    with a 10-second timeout per lookup. Response is mapped to GISParcel.
    """
    TIMEOUT_SECONDS = 10
    connector_name = "dupage_gis"
    market = "dupage_il"

    def lookup_by_address(self, address: str) -> Optional[GISParcel]: ...
    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]: ...
```

The DuPage GIS connector is registered in `GISConnectorRegistry` (a simple dict keyed by market). The `LeadIngestionService` resolves the connector from the registry using the lead's market/state; if no connector is registered for a market, GIS enrichment is skipped and `needs_skip_trace` is left unchanged.

### 3. Deduplication Engine

**File**: `backend/app/services/deduplication_engine.py`

```python
@dataclass
class DeduplicationResult:
    outcome: Literal["created", "updated", "conflict"]
    lead: Lead
    conflict_detail: Optional[dict]  # field conflicts logged to ImportJob

class DeduplicationEngine:
    """Platform-wide deduplication for all ingestion sources."""

    NORMALIZATION_PATTERN = re.compile(r'[^\w\s]')  # strip punctuation
    WHITESPACE_PATTERN = re.compile(r'\s+')          # collapse whitespace

    def normalize_address(self, address: str) -> str:
        """Uppercase, strip punctuation, collapse whitespace."""
        ...

    def find_existing_lead(
        self, property_street: str, pin: Optional[str]
    ) -> Optional[Lead]:
        """Check address (normalized) then PIN as secondary key."""
        ...

    def merge_lead(
        self, existing: Lead, incoming: dict, import_job_id: int
    ) -> DeduplicationResult:
        """Apply non-null incoming fields to existing lead.
        Preserve existing non-null values; log field conflicts.
        """
        ...

    def process_record(
        self, record: dict, import_job_id: int
    ) -> DeduplicationResult:
        """Full deduplication flow: find → merge or create."""
        ...
```

### 4. Lead Ingestion Service

**File**: `backend/app/services/lead_ingestion_service.py`

The `LeadIngestionService` is the central orchestrator. It owns the `ImportJob` lifecycle, delegates to per-source handlers, and coordinates GIS enrichment.

```python
VALID_SOURCE_TYPES = frozenset({
    "foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"
})

VALID_DATA_SOURCES = frozenset({
    "dupage_gis", "dupage_sheriff", "dupage_recorder",
    "tax_distress_source", "manual_csv"
})

GIS_ENRICHED_SOURCE_TYPES = frozenset({"foreclosure", "tax_distress", "manual_distress"})

class LeadIngestionService:
    def __init__(
        self,
        dedup_engine: DeduplicationEngine,
        gis_registry: GISConnectorRegistry,
    ): ...

    def ingest_foreclosure(
        self, records: list[dict], owner_user_id: str
    ) -> ImportJob: ...

    def ingest_long_owned(
        self, records: list[dict], owner_user_id: str
    ) -> ImportJob: ...

    def ingest_absentee_owner(
        self, records: list[dict], owner_user_id: str
    ) -> ImportJob: ...

    def ingest_tax_distress(
        self, records: list[dict], owner_user_id: str
    ) -> ImportJob: ...

    def process_csv(
        self, job_id: int, file_path: str, owner_user_id: str
    ) -> ImportJob: ...

    def _enrich_with_gis(
        self, lead: Lead, connector: GISConnector, import_job_id: int
    ) -> None:
        """Attempt GIS lookup; populate null fields if match found.
        Times out at 10s. Logs outcome to ImportJob regardless.
        Never raises — errors are caught and logged.
        """
        ...

    def _set_skip_trace_flag(self, lead: Lead) -> None:
        """Set needs_skip_trace per Req 1.5 (creation only)."""
        ...
```

Each handler (e.g. `ForeclosureHandler`) is a plain function or small class that maps a source record dict to the Lead field dict. Handlers do not touch the database directly; they return a normalized dict and the service passes it to `DeduplicationEngine.process_record()`.

### 5. Ingestion Controller

**File**: `backend/app/controllers/ingestion_controller.py`  
**Blueprint prefix**: `/api/ingestion`

```
POST /api/ingestion/foreclosure        → ingest_foreclosure
POST /api/ingestion/long-owned         → ingest_long_owned
POST /api/ingestion/absentee-owner     → ingest_absentee_owner
POST /api/ingestion/tax-distress       → ingest_tax_distress
POST /api/ingestion/csv                → csv_upload (sync ≤500 / async >500)
GET  /api/ingestion/jobs/<job_id>      → get_import_job (status polling)
```

All ingestion endpoints require `owner_user_id` in the request body (validated via `IngestionRequestSchema`). The controller resolves the user from the `X-User-Id` header as the authenticated caller; `owner_user_id` is the target account that will own the created leads (may differ from the caller for admin/seeding operations).

**CSV upload specifics**: The endpoint accepts `multipart/form-data`. File size is validated before parsing (reject >10 MB with 400). Row count is determined by streaming the first 501 rows; if count ≤ 500, processing runs synchronously and returns 200; otherwise, the file is written to a temp path, Celery task is enqueued, and 202 is returned.

### 6. Extended Lead List Filters

**Existing file**: `backend/app/controllers/lead_controller.py`  
**Schema change**: `backend/app/schemas.py` — `LeadListQuerySchema`

Two new optional fields added to `LeadListQuerySchema`:

```python
VALID_SOURCE_TYPES = [
    "foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"
]

source_type = fields.Str(
    load_default=None,
    validate=validate.OneOf(VALID_SOURCE_TYPES),
    allow_none=True,
)
owner_user_id = fields.Str(load_default=None, validate=validate.Length(max=36))
```

The lead list query in `lead_controller.py` adds `.filter(Lead.source_type == source_type)` and `.filter(Lead.owner_user_id == owner_user_id)` conditionally when each param is present.

### 7. Frontend Filter Controls

**Existing component**: `frontend/src/components/LeadList.tsx` (or equivalent lead list view)  
**Types file**: `frontend/src/types/index.ts`

`PropertyListFilters` gains two new optional fields:

```typescript
source_type?: 'foreclosure' | 'long_owned' | 'absentee_owner' | 'tax_distress' | 'manual_distress'
owner_user_id?: string
```

UI additions:
- `source_type`: MUI `Select` component with "All Sources" as the default empty option, plus one option per allowed value. Placed in the existing filter bar alongside `property_type` and `lead_category`.
- `owner_user_id`: MUI `TextField` with a placeholder "Owner user ID". Placed in the filter bar after `source_type`.

Both filters are passed as query params to the `GET /api/leads/` endpoint via the existing React Query hook. Changing either filter resets the page to 1.

---

## Data Models

### leads table — new columns (migration)

**File**: `backend/alembic_migrations/versions/xxxx_add_dupage_lead_columns.py`

```python
def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS tax_distress_data JSONB
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS manual_priority INTEGER
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_source_type
        ON leads(source_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id_source_type
        ON leads(owner_user_id, source_type)
    """)

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_owner_user_id_source_type")
    op.execute("DROP INDEX IF EXISTS ix_leads_source_type")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS manual_priority")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS tax_distress_data")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS source_type")
```

### Property (Lead) model additions

**File**: `backend/app/models/lead.py`

Three new columns added to the `Property` class after the existing `data_source` column:

```python
# Ingestion source type (platform-wide)
source_type = db.Column(db.String(50), nullable=True, index=True)

# Tax distress metadata (scoring-only, never surfaced in notes/outreach)
# Expected JSON shape: {
#   "signal_type": "tax_delinquency" | "tax_sale",
#   "delinquent_amount": float | null,
#   "tax_year": int | null
# }
tax_distress_data = db.Column(db.JSON, nullable=True)

# Manual priority override (1-5, set by CSV upload)
manual_priority = db.Column(db.Integer, nullable=True)
```

`manual_priority` aligns with the existing `_manual_priority_score` stub in `DeterministicScoringEngine`, which already reads `getattr(lead, "manual_priority", None)`. No change to the engine method is needed beyond the column existing.

### ImportJob model addition

**File**: `backend/app/models/import_job.py`

One new column, added via a separate migration:

```python
# Which source type was ingested in this job
source_type = db.Column(db.String(50), nullable=True)
```

**Migration** (`backend/alembic_migrations/versions/xxxx_add_import_job_source_type.py`):

```python
def upgrade():
    op.execute("""
        ALTER TABLE import_jobs
        ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)
    """)

def downgrade():
    op.execute("ALTER TABLE import_jobs DROP COLUMN IF EXISTS source_type")
```

### tax_distress_data JSON structure

```json
{
  "signal_type": "tax_delinquency",
  "delinquent_amount": 4250.00,
  "tax_year": 2022
}
```

Both `delinquent_amount` and `tax_year` may be `null` when the source data omits them. `signal_type` is always one of `"tax_delinquency"` or `"tax_sale"` and is always present.

### Marshmallow Schema additions

**File**: `backend/app/schemas.py`

New schemas added:

```python
VALID_SOURCE_TYPES = [
    "foreclosure", "long_owned", "absentee_owner", "tax_distress", "manual_distress"
]

class IngestionRequestSchema(RequestSchema):
    """Base schema for all ingestion endpoints."""
    owner_user_id = fields.Str(required=True, validate=validate.Length(min=1, max=36))
    records = fields.List(fields.Dict(), required=True, validate=validate.Length(min=1))

class CSVUploadQuerySchema(RequestSchema):
    """Query params for CSV upload endpoint."""
    owner_user_id = fields.Str(required=True, validate=validate.Length(min=1, max=36))

class ImportJobResponseSchema(Schema):
    """Serializer for ImportJob status polling response."""
    id = fields.Int(dump_only=True)
    status = fields.Str(dump_only=True)
    source_type = fields.Str(dump_only=True, allow_none=True)
    rows_processed = fields.Int(dump_only=True)
    rows_imported = fields.Int(dump_only=True)
    rows_skipped = fields.Int(dump_only=True)
    error_log = fields.List(fields.Dict(), dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    completed_at = fields.DateTime(dump_only=True, allow_none=True)
```

`LeadListQuerySchema` gains the two new optional filter fields (see §Components above).

`LeadDetailResponseSchema` gains three new dump fields:
```python
source_type = fields.Str(allow_none=True)
tax_distress_data = fields.Dict(allow_none=True)
manual_priority = fields.Int(allow_none=True)
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: source_type assignment is always valid

*For any* ingestion call with a valid `source_type` input, the resulting lead record's `source_type` field equals the input value exactly, and that value is one of `{foreclosure, long_owned, absentee_owner, tax_distress, manual_distress}`.

**Validates: Requirements 1.1, 1.6**

### Property 2: Invalid source_type is always rejected

*For any* string that is not in the allowed `source_type` set, the Lead_Ingestion_Service returns an error response and creates no lead record.

**Validates: Requirements 1.7**

### Property 3: owner_user_id propagates to every created lead

*For any* ingestion request containing a `user_id`, every lead record created in that request has its `owner_user_id` set to that exact `user_id` value.

**Validates: Requirements 1.2**

### Property 4: needs_skip_trace follows contact-presence rule

*For any* newly created lead, if both `phone_1` and `email_1` are null or empty string then `needs_skip_trace` is `true`; if at least one is a non-empty string then `needs_skip_trace` is `false`. On an update to an existing lead, `needs_skip_trace` is unchanged regardless of incoming contact data.

**Validates: Requirements 1.5**

### Property 5: Deduplication — same address never creates a second lead

*For any* property address that already exists in the database, re-ingesting that address (with any case variation or extra whitespace) results in an update to the existing record, not a new record. The total count of leads with that normalized address remains exactly 1.

**Validates: Requirements 2.5, 7.1, 7.3, 7.4**

### Property 6: Existing non-null field values are never overwritten

*For any* field on an existing lead that is non-null, providing a different non-null value for that field in a subsequent ingestion run leaves the original value unchanged and adds a conflict entry to the ImportJob error log.

**Validates: Requirements 7.5**

### Property 7: long_owned threshold boundary is respected

*For any* property acquisition date that is 15 or more full calendar years before the ingestion date, ingestion creates or updates a lead with `source_type = long_owned`. *For any* acquisition date that is fewer than 15 full calendar years before the ingestion date, the record is skipped.

**Validates: Requirements 3.1, 3.4**

### Property 8: Absentee owner detection uses normalized address comparison

*For any* property record where the owner mailing address and the property address differ after uppercasing, trimming whitespace, and removing punctuation, the lead is created or updated with `source_type = absentee_owner`. Records where normalized addresses are equal are not tagged as absentee.

**Validates: Requirements 4.1**

### Property 9: tax_distress_data stores all required fields from source

*For any* tax distress ingestion record, the stored `tax_distress_data` JSON contains a `signal_type` matching the source value, a `delinquent_amount` matching the source value (or null if absent), and a `tax_year` matching the source value (or null if absent).

**Validates: Requirements 5.3, 5.6**

### Property 10: Tax distress language never appears in notes

*For any* lead created or updated by a `tax_distress` source ingestion, the `notes` field contains none of the strings: `tax delinquency`, `tax sale`, `delinquent`, or any delinquent amount or tax year value from `tax_distress_data`.

**Validates: Requirements 5.4**

### Property 11: manual_priority validated and stored within bounds

*For any* CSV row with a `manual_priority` value that is an integer in `[1, 5]`, the resulting lead has `manual_priority` set to that value. *For any* `manual_priority` value that is absent, non-integer, or outside `[1, 5]`, the field is not set on the lead (remains null or unchanged) and a warning is logged.

**Validates: Requirements 6.6**

### Property 12: source_type filter returns only matching leads

*For any* `source_type` filter value passed to `GET /api/leads/`, every lead in the response has a `source_type` column value equal to that filter value. No lead with a different `source_type` (including null) appears in the filtered result set.

**Validates: Requirements 11.1, 11.3**

### Property 13: owner_user_id filter returns only matching leads

*For any* `owner_user_id` filter value passed to `GET /api/leads/`, every lead in the response has `owner_user_id` equal to that filter value. No lead owned by a different user appears in the result set.

**Validates: Requirements 11.2**

### Property 14: source_type_distress dimension is exactly 10 points for qualifying source types

*For any* residential lead with `source_type` in `{foreclosure, tax_distress, long_owned}`, the `source_type_distress` dimension in `score_details` is exactly 10 points, regardless of any other lead fields. The dimension never exceeds 10 regardless of how many qualifying signals are present simultaneously.

**Validates: Requirements 12.1**

### Property 15: tax_distress_data bonus adds exactly 5 points

*For any* lead with a non-null `tax_distress_data` field and a qualifying `source_type`, the `source_type_distress` dimension is 5 points higher than an equivalent lead with `tax_distress_data = null`. The combined cap (source_type base 10 + bonus 5 = 15) is enforced.

**Validates: Requirements 12.2**

### Property 16: Tax distress language absent from LeadScore outputs

*For any* lead that carries `tax_distress_data`, the resulting `LeadScore` record's `top_signals` array and `recommended_action` field contain none of the strings: `tax_delinquency`, `tax_sale`, `delinquent`, or any value from `tax_distress_data`.

**Validates: Requirements 12.3**

### Property 17: absentee_owner source_type always scores full 10 points in absentee dimension

*For any* lead with `source_type = absentee_owner`, the `absentee_owner` scoring dimension is 10 points regardless of whether the mailing address field differs from the property address field.

**Validates: Requirements 12.5**

---

## Error Handling

### Ingestion errors

| Scenario | Behavior |
|---|---|
| Invalid `source_type` | Reject entire request; 400 with `{ error: "Invalid source_type: <value>" }` |
| ImportJob creation fails | Abort run; return 500 with error detail |
| GIS lookup timeout (>10s) | Log error + lead address + source_type; leave GIS fields null; continue batch |
| GIS lookup returns no match | Set `needs_skip_trace = true`; append `"GIS match not found"` to notes; continue |
| GIS service unavailable | Log error; skip enrichment for affected records; do not modify `needs_skip_trace` |
| Deduplication conflict (PIN mismatch) | Log to ImportJob `error_log`; skip record; continue batch |
| Row missing required fields | Log row number + reason; increment `rows_skipped`; continue |
| CSV > 10 MB | 400 before any processing begins |
| CSV not valid CSV | 400 before any processing begins |

### Scoring errors

| Scenario | Behavior |
|---|---|
| Unknown `source_type` in scoring | `source_type_distress` dimension scores 0; no exception raised |
| `tax_distress_data` malformed JSON | Log warning; treat as null for scoring; do not raise |
| `manual_priority` outside [0, max_points] | `_manual_priority_score` clamps to `[0, max_points]` (existing behavior) |

### API validation errors

All validation errors from Marshmallow schemas return 400 with the standard project error envelope:
```json
{ "error": { "message": "...", "fields": { "field_name": ["error detail"] } } }
```

Invalid `source_type` filter on `GET /api/leads/` returns:
```json
{ "error": { "message": "source_type must be one of: foreclosure, long_owned, absentee_owner, tax_distress, manual_distress" } }
```

---

## Testing Strategy

### Unit tests (pytest + example-based)

- `tests/test_deduplication_engine.py`: address normalization logic, PIN conflict detection, field merge behavior with concrete examples.
- `tests/test_lead_ingestion_service.py`: per-handler field mapping, GIS enrichment (mocked connector), ImportJob lifecycle, CSV row count branching (499/500/501 row threshold).
- `tests/test_deterministic_scoring_engine.py`: new `source_type_distress` dimension examples for each qualifying and non-qualifying source type; `absentee_owner` short-circuit; tax distress signal absence from outputs.
- `tests/test_ingestion_controller.py`: HTTP 400 on invalid source_type; 202 on large CSV; 200 on small CSV; filter params propagated correctly.
- `tests/test_lead_controller.py` (existing, extended): `source_type` and `owner_user_id` filter params applied to query; invalid `source_type` returns 400.

### Property-based tests (pytest + Hypothesis)

Each property test maps to one or more Correctness Properties above. All are configured to run a minimum of 100 trials via `@settings(max_examples=100)`.

**File**: `tests/test_dupage_lead_database_properties.py`

Tag format used in comments: `Feature: dupage-lead-database, Property <N>: <title>`

Properties covered by Hypothesis tests:
- **Property 1** — `st.sampled_from(VALID_SOURCE_TYPES)` as input; assert output `source_type` matches. **Validates: Requirements 1.1, 1.6**
- **Property 2** — `st.text().filter(lambda s: s not in VALID_SOURCE_TYPES)`; assert error, no lead created. **Validates: Requirements 1.7**
- **Property 3** — `st.text(min_size=1, max_size=36)` as `user_id`; assert `owner_user_id` propagates. **Validates: Requirements 1.2**
- **Property 4** — `st.one_of(st.none(), st.just(""), st.text(min_size=1))` for phone_1 and email_1; assert `needs_skip_trace` logic. **Validates: Requirements 1.5**
- **Property 5** — `st.text(min_size=5, max_size=200)` as address; insert lead, re-ingest with case/whitespace variants; assert count == 1. **Validates: Requirements 2.5, 7.1, 7.3, 7.4**
- **Property 6** — `st.fixed_dictionaries(...)` for existing lead fields + incoming overrides; assert existing non-null values preserved. **Validates: Requirements 7.5**
- **Property 7** — `st.dates(max_value=date.today())` as acquisition_date; assert 15-year boundary. **Validates: Requirements 3.1, 3.4**
- **Property 8** — `st.tuples(st.text(), st.text())` as (property_address, mailing_address); assert absentee detection after normalization. **Validates: Requirements 4.1**
- **Property 9** — `st.fixed_dictionaries({"signal_type": ..., "delinquent_amount": ..., "tax_year": ...})`; assert stored data matches. **Validates: Requirements 5.3, 5.6**
- **Property 10** — Any tax distress ingestion; assert forbidden strings absent from `notes`. **Validates: Requirements 5.4**
- **Property 11** — `st.integers()` as manual_priority; assert [1,5] stored, others skipped. **Validates: Requirements 6.6**
- **Properties 12, 13** — `st.builds(...)` for leads with varied source_type/owner_user_id; assert filter correctness. **Validates: Requirements 11.1, 11.2, 11.3**
- **Properties 14, 15, 16, 17** — `st.builds(Lead, source_type=...)` with mocked DB; assert scoring dimension values and signal absence. **Validates: Requirements 12.1, 12.2, 12.3, 12.5**

### Integration tests

- Migration idempotency: run migration twice against a test database; verify no error and columns/indexes exist.
- CSV async path: upload a 501-row CSV against a test app with Celery in `task_always_eager` mode; assert 202 response and ImportJob completion.
- GIS connector timeout: mock the GIS HTTP call to exceed 10s; assert lead created with null GIS fields and `GIS match not found` in notes.

### Smoke tests

- Column and index existence after migration (Requirement 10.1–10.5).
