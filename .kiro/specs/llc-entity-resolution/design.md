# LLC Entity Resolution — Design

## Pipeline

```
Import IL SOS Transparency Act zips → il_sos_llc_* tables
Detect entity primary
  → jurisdiction IL?
      no  → unsupported_jurisdiction
      yes → IllinoisSosBulkProvider.lookup_llc (DB only)
            → upsert Organization + parties
            → select natural person party
            → ContactService._upsert_named_owner(is_primary=True)
            → SkipTraceEnqueue.enqueue
```

## Canonical modules

| Module | Role |
|--------|------|
| `entity_resolution_service.py` | Orchestrator / status writer |
| `entity_lookup/ilsos_bulk.py` | Free default provider |
| `entity_lookup/ilsos_parser.py` / `ilsos_import_service.py` | Fixed-width parse + load |
| `entity_lookup/factory.py` | Default `ilsos_bulk` |
| `entity_lookup/opencorporates.py` | Paid adapter (not default) |
| `skip_trace_enqueue.py` | Skip-trace handoff (manual in v1) |
| `organization_party.py` | Filing parties |
| `entity_resolution_controller.py` | HTTP API |
| `import_il_sos_llc_bulk.py` | Ops import |

## Status enum

`pending | resolved | no_match | unsupported_jurisdiction | error`

`entity_lookup_person_found` distinguishes RA-only resolved filings.

## Future skip-trace

Replace `SkipTraceEnqueue.enqueue` implementation with a vendor
`SkipTraceService`. Entity resolution and individual-owner skip-trace both call
the same enqueue entry point.
