# Design Document: Source-Agnostic CRM Queues

## Overview

The platform's Actionable Lead Command Center currently exposes 7 work queues that are
only populated by HubSpot-sourced leads. DuPage County leads (68,565 records) share
the same `leads` table but are invisible in every queue. This feature makes all 7
queues source-agnostic by evaluating universal Lead model fields instead of HubSpot-
specific join paths.

Four code locations require changes:

1. **`QueueService`** — rewrite every queue filter (both count and paginated) to operate
   solely on `lead_status`, `recommended_action`, `is_warm`, `review_required`,
   `has_property_match`, and open-task subqueries (LeadTask / Task / TaskAssociation).
   Remove the `hubspot_signals` join from the Previously Warm queue.

2. **`LeadIngestionService`** — at DuPage import time, set `has_property_match` and
   `review_required` correctly based on GIS lookup results and data-completeness checks.

3. **HubSpot signal pipeline** — in `run_extract_hubspot_signals` (Task 7) and optionally
   `HubSpotSignalExtractorService.apply_suppression`, write `is_warm = True` on the
   Lead when a `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED` signal is detected.

4. **`App.tsx` sidebar** — split the Properties section header into two separate click
   targets: the label text navigates to `/properties`; the chevron icon only toggles
   the expand/collapse state.

No schema changes are required. All relevant columns (`is_warm`, `review_required`,
`review_reason`, `has_property_match`) already exist on the `Property` / `Lead` model.

---

## Architecture

```text
┌─────────────────────────────────────────────────┐
│              React Frontend                     │
│  App.tsx                                        │
│  ├── Properties label  → navigate('/properties')│
│  └── Chevron icon      → toggleSection()        │
│                                                 │
│  QueueSidebar / Queue components                │
│  └── GET /api/queues/counts  (badge counts)     │
│  └── GET /api/queues/<name>  (paginated rows)   │
└────────────────────┬────────────────────────────┘
                     │  REST / JSON
┌────────────────────▼────────────────────────────┐
│              Flask Backend                      │
│  QueueController (existing)                     │
│  └── QueueService (refactored)                  │
│       ├── filter on Lead model columns only     │
│       └── no hubspot_signals join in warm queue │
│                                                 │
│  Lead Ingestion Pipeline                        │
│  └── LeadIngestionService (updated)             │
│       ├── _enrich_with_gis  → has_property_match│
│       └── _set_review_required_flag (new)       │
│                                                 │
│  HubSpot Signal Pipeline                        │
│  └── run_extract_hubspot_signals (updated)      │
│       └── sets lead.is_warm = True on warm sigs │
└─────────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│            PostgreSQL: leads table              │
│  lead_status, recommended_action (enum cols)    │
│  is_warm, review_required, has_property_match   │
│  lead_tasks, tasks, task_associations           │
└─────────────────────────────────────────────────┘
```

The overall architecture does not change. This is a targeted refactor of filter
predicates and two ingestion side-effects. No new tables, endpoints, or services are
introduced.

---

## Components and Interfaces

### 2.1 QueueService refactor (`backend/app/services/queue_service.py`)

**Problem**: `_count_previously_warm` and `get_previously_warm` join
`hubspot_signals` directly. This means DuPage leads (which never have HubSpot signals)
are always excluded from the Previously Warm queue. The `No Next Action` recommended_action
allow-list is also narrower than the requirements specify.

**Changes**:

**Previously Warm** — replace the `hubspot_signals` join with a direct column filter:

```python
# BEFORE (joins hubspot_signals)
def _count_previously_warm(self, ninety_days_ago):
    subq = select(Lead.id).join(HubSpotSignal, ...).filter(...).distinct().subquery()
    return db.session.query(func.count()).select_from(subq).scalar()

# AFTER (column-only filter)
def _count_previously_warm(self) -> int:
    return self._base_query().filter(Lead.is_warm.is_(True)).count()
```

The `ninety_days_ago` parameter is removed because the `is_warm` flag is a permanent
marker (never cleared). The 90-day rolling window concept no longer applies.

`get_previously_warm` is updated the same way:

```python
def get_previously_warm(self, page=1, per_page=20, ...):
    query = self._base_query().filter(Lead.is_warm.is_(True))
    ...
```

**No Next Action** — expand the `recommended_action` allow-list per Req 1.1/1.4:

```python
# AFTER — adds 'ready_for_outreach' and 'add_contact_info' to the allow-list
or_(
    Lead.recommended_action.is_(None),
    Lead.recommended_action.in_(['create_task', 'ready_for_outreach', 'add_contact_info']),
)
```

**`get_counts()` signature** — remove the `ninety_days_ago` argument from the
`_count_previously_warm` call:

```python
def get_counts(self) -> dict[str, int]:
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    return {
        "todays_action":          self._count_todays_action(today),
        "previously_warm":        self._count_previously_warm(),   # no date arg
        "follow_up_overdue":      self._count_follow_up_overdue(today, seven_days_ago),
        "no_next_action":         self._count_no_next_action(),
        "needs_review":           self._count_needs_review(),
        "do_not_contact":         self._count_do_not_contact(),
        "missing_property_match": self._count_missing_property_match(),
    }
```

All other queues (Today's Action, Follow-Up Overdue, No Next Action, Needs Review,
Do Not Contact, Missing Property Match) already use universal Lead columns. Their
filter logic is correct; only the Previously Warm and No Next Action allow-list need
updating.

The `HubSpotSignal` import at the top of `queue_service.py` can be removed once the
Previously Warm query is rewritten — no other method uses it.

---

### 2.2 LeadIngestionService updates (`backend/app/services/lead_ingestion_service.py`)

**Problem**: The existing `_enrich_with_gis` method sets `has_property_match = True`
on a GIS hit but **never sets it to `False`** on a GIS miss. The `review_required` flag
is never set by the ingestion service at all (it is currently set only by
`HubSpotTimelineImportService.import_activities_for_lead` for HubSpot activity events).

**Changes**:

#### `_enrich_with_gis` — set `has_property_match = False` on no-match

The existing "no match" branch only sets `needs_skip_trace = True` and appends a note.
Add `lead.has_property_match = False` here:

```python
if parcel is None:
    lead.needs_skip_trace = True
    lead.has_property_match = False          # ← NEW (Req 6.2, 6.3)
    _append_note(lead, 'GIS match not found')
    return outcome
```

The guard in Req 6.3 ("if GIS not attempted, do not set False") is already satisfied
because `_enrich_with_gis` is only called when a `connector` is found in
`self.gis_registry`. If no connector exists the call is skipped entirely.

The guard in Req 6.4 ("do not override True to False") is satisfied because
`has_property_match` is only set to `False` in the no-match branch; the match branch
sets it to `True` and returns without ever reaching the no-match branch.

#### New helper `_set_review_required_flag`

Add a private helper that evaluates the three-field completeness rule and is called
immediately after `_set_skip_trace_flag` in every ingestion method:

```python
def _set_review_required_flag(self, lead, is_creation: bool) -> None:
    """Set or clear review_required based on critical field completeness (Req 5.2–5.4).

    Rule:
    - On creation: set True + reason only when all three of phone_1, email_1,
      county_assessor_pin are null or empty.
    - On update: clear flag (set False, reason=None) if all three fields are now
      populated; otherwise leave flag unchanged.
    """
    has_phone = bool(lead.phone_1 and str(lead.phone_1).strip())
    has_email = bool(lead.email_1 and str(lead.email_1).strip())
    has_pin   = bool(lead.county_assessor_pin and str(lead.county_assessor_pin).strip())

    all_missing = not has_phone and not has_email and not has_pin
    all_present = has_phone and has_email and has_pin

    if is_creation:
        if all_missing:
            lead.review_required = True
            lead.review_reason   = 'Missing phone, email, and county PIN'
        # Otherwise leave False (default) — Req 5.3
    else:
        # On update: clear if all three are now present
        if all_present and lead.review_required:
            lead.review_required = False
            lead.review_reason   = None
        # Otherwise leave review_required unchanged — Req 5.4
```

This helper is called for every source type inside each `ingest_*` method after the
dedup result is resolved, before `db.session.add(lead)`:

```python
# inside ingest_foreclosure, ingest_tax_distress, ingest_long_owned,
# ingest_absentee_owner, process_csv — all DuPage ingestion paths:
self._set_skip_trace_flag(lead, is_creation)
self._set_review_required_flag(lead, is_creation)   # ← NEW
lead.last_import_job_id = job.id
db.session.add(lead)
```

---

### 2.3 HubSpot signal pipeline — `is_warm` flag (`backend/app/tasks/hubspot_tasks.py`)

**Problem**: `run_extract_hubspot_signals` (Task 7) persists `HubSpotSignal` records
but never writes `is_warm = True` on the associated Lead. As a result the Previously
Warm queue (now filtered by `is_warm`) will show zero HubSpot leads after the refactor
unless this is fixed simultaneously.

**Change**: After persisting signals for each interaction, check whether any signal
in that batch is `PRIOR_WARM_CONVERSATION` or `APPOINTMENT_OCCURRED`. If so, and if the
Lead's `is_warm` is not already `True`, set it (one-way flag — never cleared):

```python
# inside run_extract_hubspot_signals, in the per-interaction try block,
# after: db.session.commit() — persist signals first so suppression also works

WARM_SIGNAL_TYPES = frozenset({'PRIOR_WARM_CONVERSATION', 'APPOINTMENT_OCCURRED'})

warm_signals = [s for s in signals if s.signal_type in WARM_SIGNAL_TYPES]
if warm_signals:
    from app.models import Lead as _Lead
    lead_obj = _Lead.query.get(lead_id)
    if lead_obj is not None and not lead_obj.is_warm:
        lead_obj.is_warm = True
        db.session.add(lead_obj)
        db.session.commit()
```

The same check should be added inside `HubSpotSignalExtractorService.apply_suppression`
is not the right place — that method handles suppression, not warmth. The best
location is `run_extract_hubspot_signals` immediately after calling
`extractor.apply_suppression(signals)`.

**One-way guarantee (Req 9.3)**: The guard `if not lead_obj.is_warm` ensures a True
value is never changed. No code path in the pipeline ever explicitly sets
`is_warm = False`; the column's default is `False` and it is never overwritten to
`False` by any sync run.

---

### 2.4 Frontend sidebar fix (`frontend/src/App.tsx`)

**Problem**: The Properties section header is a single `ListItemButton` whose
`onClick` calls `toggleSection(section.path)`. Clicking anywhere on the row — including
the label text — only collapses/expands; it does not navigate to `/properties`.

**Change**: Replace the single `ListItemButton` with a layout row that separates the
label click target from the chevron click target. The heading row is styled to look
identical to the current design.

Only the "Properties" section needs dual behavior; the "Analysis" section header
is left unchanged (Req 10.3).

The cleanest implementation is a conditional inside the `NAV_SECTIONS.map` render loop:

```tsx
{NAV_SECTIONS.map((section) => (
  <Box key={section.path}>
    {/* Section header */}
    {section.path === '/properties' ? (
      // Properties: label navigates, chevron toggles — Req 10.1
      <Box
        sx={{ display: 'flex', alignItems: 'center', py: 1.5, cursor: 'pointer' }}
      >
        <ListItemButton
          component={Link}
          to={section.path}
          onClick={() => isMobile && setDrawerOpen(false)}
          sx={{ py: 0, flexGrow: 1, '&:hover': { bgcolor: 'transparent' } }}
          disableRipple={false}
          aria-label={`Navigate to ${section.label}`}
        >
          <ListItemIcon sx={{ minWidth: 40 }}>{section.icon}</ListItemIcon>
          <ListItemText
            primary={section.label}
            primaryTypographyProps={{ fontWeight: 600 }}
          />
        </ListItemButton>
        <IconButton
          size="small"
          onClick={(e) => { e.stopPropagation(); toggleSection(section.path) }}
          aria-label={expandedSections[section.path] ? 'Collapse section' : 'Expand section'}
          sx={{ mr: 1 }}
        >
          {expandedSections[section.path] ? <ExpandLess /> : <ExpandMore />}
        </IconButton>
      </Box>
    ) : (
      // All other sections: single ListItemButton toggles collapse only
      <ListItemButton
        onClick={() => toggleSection(section.path)}
        sx={{ py: 1.5 }}
      >
        <ListItemIcon sx={{ minWidth: 40 }}>{section.icon}</ListItemIcon>
        <ListItemText
          primary={section.label}
          primaryTypographyProps={{ fontWeight: 600 }}
        />
        {expandedSections[section.path] ? <ExpandLess /> : <ExpandMore />}
      </ListItemButton>
    )}
    <Collapse in={expandedSections[section.path]} timeout="auto" unmountOnExit>
      {/* ...existing group/item rendering unchanged... */}
    </Collapse>
    <Divider />
  </Box>
))}
```

`IconButton` is already imported from MUI in `App.tsx` (used in the mobile menu).
`Link` is already imported from `react-router-dom`.

---

## Data Models

No schema changes are required. All necessary columns already exist:

| Column | Table | Type | Existing default |
|---|---|---|---|
| `is_warm` | `leads` | `BOOLEAN NOT NULL` | `false` |
| `review_required` | `leads` | `BOOLEAN NOT NULL` | `false` |
| `review_reason` | `leads` | `VARCHAR(255)` | `null` |
| `has_property_match` | `leads` | `BOOLEAN NOT NULL` | `false` |
| `lead_status` | `leads` | enum | `'new'` |
| `recommended_action` | `leads` | enum nullable | `null` |

The `has_property_match` column defaults to `False`. This means DuPage leads that
were ingested before this feature was deployed will have `has_property_match = False`
and will correctly appear in the Missing Property Match queue for researcher triage.
A one-time backfill (separate task) can update leads that were GIS-matched before the
column was being set — that is out of scope for this design.

Similarly, `is_warm = False` by default. Existing HubSpot leads with warm signals
will be picked up and marked `is_warm = True` on the next `run_extract_hubspot_signals`
run (Task 7 in the post-import pipeline), which is idempotent.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid
executions of a system — essentially, a formal statement about what the system should
do. Properties serve as the bridge between human-readable specifications and
machine-verifiable correctness guarantees.*

### Property 1: No Next Action filter predicate

*For any* Lead in the database, the Lead appears in the No Next Action queue if and
only if: its `lead_status` is in `('new', 'active')` AND its `recommended_action` is
`null` or in `('create_task', 'ready_for_outreach', 'add_contact_info')` AND it has no
open or overdue LeadTask and no open or overdue Task (via TaskAssociation or direct
`lead_id`).

**Validates: Requirements 1.1, 1.3, 1.4**

---

### Property 2: Badge counts equal paginated totals

*For any* state of the leads table (arbitrary set of leads with arbitrary field values),
`QueueService.get_counts()` returns a count for each of the 7 queues that equals
the `total` value returned by the corresponding paginated `get_*` method called with
no pagination constraints.

**Validates: Requirements 1.5, 2.3, 3.4, 4.5, 5.5, 6.5, 12.1**

---

### Property 3: Previously Warm queue is exactly the set of `is_warm = True` leads

*For any* set of leads, the Previously Warm queue contains exactly those leads where
`is_warm` is `True` — no more, no fewer. No lead with `is_warm = False` appears in
the queue; no lead with `is_warm = True` is excluded.

**Validates: Requirements 4.1, 4.2**

---

### Property 4: Warm signal processing sets `is_warm = True` (one-way)

*For any* Lead processed through the HubSpot signal pipeline, if any associated
HubSpotSignal has `signal_type` in `('PRIOR_WARM_CONVERSATION', 'APPOINTMENT_OCCURRED')`,
then after pipeline completion `lead.is_warm` is `True`. Conversely, if no such signal
exists for a Lead, `lead.is_warm` is not changed by the pipeline. A Lead that had
`is_warm = True` before a sync run shall never have `is_warm = False` after that run,
regardless of the signals present.

**Validates: Requirements 4.3, 9.1, 9.2, 9.3**

---

### Property 5: `review_required` creation rule

*For any* newly ingested DuPage Lead, `review_required` is `True` if and only if all
three of `phone_1`, `email_1`, and `county_assessor_pin` are null or empty strings. If
at least one of those fields has a non-empty value, `review_required` remains `False`.

**Validates: Requirements 5.2, 5.3**

---

### Property 6: `review_required` update rule

*For any* DuPage Lead that has `review_required = True`, after an update to that Lead:
if all three of `phone_1`, `email_1`, and `county_assessor_pin` are populated and
non-empty, then `review_required` becomes `False`; if any of the three fields remain
null or empty, `review_required` remains `True` unchanged.

**Validates: Requirements 5.4**

---

### Property 7: GIS no-match sets `has_property_match = False`

*For any* DuPage Lead ingested when the GIS connector is configured and returns no
parcel match (lookup attempted, result is None), `has_property_match` is `False` after
ingestion. A successful GIS match that sets `has_property_match = True` is never
overridden to `False` by any subsequent no-match result in the same ingestion run.

**Validates: Requirements 6.2, 6.3, 6.4**

---

### Property 8: Missing Property Match filter predicate

*For any* Lead, the Lead appears in the Missing Property Match queue if and only if
`has_property_match` is `False` AND there is no open LeadTask of type
`'research_missing_pin'` for that Lead.

**Validates: Requirements 6.1**

---

### Property 9: Priority queues exclude No Next Action

*For any* set of leads, the intersection of (Today's Action ∪ Follow-Up Overdue) and
No Next Action is empty — no Lead appears in both a priority queue and No Next Action
simultaneously. This invariant holds because No Next Action requires the absence of any
open task and excludes `recommended_action = 'follow_up_now'`, which are the exact
preconditions that Today's Action and Follow-Up Overdue rely on.

**Validates: Requirements 11.1, 11.2, 11.3**

---

### Property 10: Owner scoping is applied uniformly

*For any* `owner_user_id` and any random population of leads with varying owners, all
7 queues (both badge counts and paginated results) contain only leads whose
`owner_user_id` matches the scoping value. No lead owned by a different user appears
in any queue.

**Validates: Requirements 12.3, 12.4**

---

## Error Handling

### QueueService

- Invalid `sort_by` column names are silently defaulted to `lead_score` via
  `getattr(Lead, sort_by, Lead.lead_score)`. No change required.
- Database errors propagate to the controller, which returns a 500 via the
  existing `@handle_errors` decorator.

### LeadIngestionService

- `_set_review_required_flag` is purely in-memory; it cannot raise database errors.
  Any exception from a calling `ingest_*` method is already caught by the outer
  `try/except` which calls `_fail_import_job`. No additional error handling needed.
- If `_enrich_with_gis` raises an exception the `except` block returns the outcome
  dict with `error` set, leaving `has_property_match` at its pre-call value (the
  default `False` for new records). This is the correct conservative behavior —
  a GIS error is not a GIS success.

### HubSpot `is_warm` setter in `run_extract_hubspot_signals`

- The `is_warm` write is wrapped in its own `try/except` to match the surrounding
  per-interaction error handling. A failure to set `is_warm` logs a warning and
  continues processing remaining interactions; the signal records are already committed.

### Frontend sidebar

- The `Link` component from React Router handles navigation errors (non-existent
  routes) with its standard fallback. The `/properties` route is already registered
  in the route table, so no 404 case exists in normal operation.

---

## Testing Strategy

### Unit tests (pytest + Hypothesis)

**QueueService** (`backend/tests/test_queue_service.py`):
- Property tests for Properties 1–3, 8–10 using Hypothesis to generate random Lead
  populations with varying `lead_status`, `recommended_action`, `is_warm`,
  `review_required`, `has_property_match`, and task states.
- Example-based tests for Req 8.1, 8.2 (multi-queue membership) and Req 11.4
  (Today's Action + Follow-Up Overdue co-membership).
- Tests run against SQLite in-memory database via the existing `app` fixture in
  `conftest.py`.

**LeadIngestionService** (`backend/tests/test_lead_ingestion_service.py`):
- Property tests for Properties 5, 6 using Hypothesis to generate combinations of
  phone_1/email_1/county_assessor_pin values (None, empty string, non-empty string)
  on creation and update paths.
- Property test for Property 7 using a mock GIS connector that returns None (no match)
  or a mock parcel object (match). The "no-GIS configured" edge case is an additional
  example test (gis_registry empty → flag not set).

**HubSpot signal pipeline** (`backend/tests/test_hubspot_tasks.py` or
`test_queue_properties.py`):
- Property test for Property 4 using Hypothesis to generate signal type combinations
  for a given lead. Assert is_warm post-run matches expected value based on whether
  PRIOR_WARM_CONVERSATION or APPOINTMENT_OCCURRED was in the signal set.
- All `db.session` calls mocked; test runs synchronously, no Celery required.

**Frontend** (`frontend/src/App.test.tsx`):
- Example-based tests using React Testing Library:
  - Click Properties label → `mockNavigate` called with `'/properties'`; section
    expanded state unchanged.
  - Click Properties chevron → `expandedSections['/properties']` toggled; navigate
    not called.
  - Click Analysis label → only `toggleSection` called; navigate not called (Req 10.3).

### Property test configuration

- Minimum 100 iterations per Hypothesis test (`@settings(max_examples=100)`).
- Tag format in test comments: `Feature: source-agnostic-crm-queues, Property N: <text>`

### Integration tests

- One integration test (`test_queue_integration.py`) that seeds both HubSpot-sourced
  and DuPage-sourced leads into the in-memory SQLite database and asserts both appear
  in the correct queues. Existing integration test file already exists; extend with
  DuPage lead fixtures.

### No property-based testing for

- The frontend sidebar behavior (UI interaction) — example tests only.
- The `get_counts()` returns all 7 keys check (Req 12.2) — single example assertion.
