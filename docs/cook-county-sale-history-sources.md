# Cook County sale-history sources (Last sale)

Command Center Last sale is filled by a **single resolve order** (fill-if-null
into `acquisition_date` for related-PIN / MyDec; primary Assessor may update):

1. **Assessor Parcel Sales** (Socrata `wvhk-k5uv`) — primary `county_assessor_pin`
2. **Assessor related / AKA PINs** — building-ownership / tax-situs / AKA ladder
   candidates on the same dataset (`wvhk-k5uv`)
3. **Illinois MyDec** (PTAX-203 on data.illinois.gov, Cook County, ~2013+)

Provenance is exposed on `sale_date_meta.source` as one of:

| Token | Meaning |
|-------|---------|
| `assessor` | Primary PIN Assessor sale |
| `assessor_related_pin` | Sibling / AKA / building-candidate PIN Assessor sale (`sale_source_pin` in enrichment metadata) |
| `mydec` | Illinois MyDec transfer declaration |

Implementation choke point:
`backend/app/services/helpers/cook_county_sale_date_resolver.py`
(wired through `CookCountyAssessorPlugin.lookup_for_lead` and Cook sale-date
verify / backfill).

Clerk `doc_no` is stored as metadata when a Socrata row includes it. **Do not**
scrape the Cook County Clerk / Recorder web UI (no public PIN API).

## Researched, not viable in-scope

| Source | Finding |
|--------|---------|
| Cook County Recorder of Deeds | No public PIN-keyed API for historical deeds |
| Redfin / Zillow / MLS scrapers | Not an open-data path; **forbidden** in enrichment plugins (CI gate) |
| Licensed commercial APIs (ATTOM, CoreLogic, …) | Out of scope for this pack (paid) |

When the full ladder returns empty, UI shows explicit **No sale found** copy via
`sale_date_meta.status === 'no_sale'` rather than a silent em dash.

## Limits

- MyDec coverage starts ~2013 — it will not fill pre-2013 title/MLS history
  (e.g. a 1993 Redfin sale).
- Related-PIN Assessor helps wrong/split/sibling PIN cases; if no candidate PIN
  has a row, Last sale stays `no_sale`.

## Follow-up

If a future open PIN-keyed deed index appears, extend the shared resolver —
do not scrape Redfin for production.

## Probe (lead 10970 / PIN 13262150360000)

After MyDec + related-PIN ladder (2026-08-04): live Assessor primary and MyDec
both return empty for this PIN. Last sale correctly remains `no_sale` under
open data (Redfin 1993 still requires a licensed feed).
