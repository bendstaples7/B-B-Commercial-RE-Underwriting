# LLC Entity Resolution (Illinois v1)

## Problem

Many properties have a primary `Contact` that is an LLC name (entity string in
`last_name`, empty `first_name`). Outreach needs a natural person.

## Goals

1. Detect entity-shaped primary contacts.
2. Look up Illinois LLC filings via **free** SOS Business Data Transparency Act
   bulk dumps (Managers / Name / Agent / Master) loaded locally.
3. Upsert `Organization` + `OrganizationParty` rows; promote a manager/member
   person to primary `Contact`.
4. Hand off to skip tracing via `SkipTraceEnqueue` (manual task in v1).
5. Mark non-Illinois jurisdictions as `unsupported_jurisdiction`.
6. Be transparent in UI/API about free-data limits (no phones, corporate RA,
   foreign LLCs, possible staleness).

## Non-goals (v1)

- Paid SOS APIs (OpenCorporates / Middesk / OpenSOSData) as the default.
- Commercial phone/email skip-trace API (separate future `SkipTraceService`).
- Multi-state SOS lookup.
- Scraping the interactive `apps.ilsos.gov` business-entity search.

## Requirements

### Detection

- R1. Treat primary contacts matching entity markers (`LLC`, `INC`, `TRUST`, …)
  as entity-shaped (reuse `owner_name_utils.is_entity_contact`).
- R2. Non-entity primaries are skipped (no provider call).

### Jurisdiction

- R3. Illinois-only lookups (`us_il`).
- R4. If property/mailing state is present and none are IL →
  `unsupported_jurisdiction` without provider call.
- R5. Missing state → attempt Illinois (portfolio default).

### Lookup + write path

- R6. Default provider is `ilsos_bulk` (local DB). Configured when bulk tables
  have rows after `import_il_sos_llc_bulk.py --apply`.
- R7. On hit: upsert Organization, replace parties, link property as owner.
- R8. Prefer first non-company manager → member → officer as primary person.
- R9. Corporate registered agent alone → status `resolved`, `person_found=false`,
  do not promote RA company to primary.
- R10. On person promotion: demote LLC contact from primary (keep linked);
  call `SkipTraceEnqueue.enqueue(lead_id, contact_id)`.

### Skip-trace handoff

- R11. v1 enqueue creates open `skip_trace_owner` LeadTask + `needs_skip_trace`.
- R12. Future vendor skip-trace replaces only `SkipTraceEnqueue` body.

### API / ops

- R13. `GET/POST /api/leads/<id>/entity-resolution`, bulk POST, Celery task,
  entity-resolution backfill script.
- R14. Empty bulk tables → 503 with import-script instructions (dry-run still allowed).
- R15. Status payload includes `provider`, `dataset_imported_at`, `limitations`.
