# Cook County sale-history sources (Last sale)

Assessor Parcel Sales (Socrata `wvhk-k5uv`) remains the only PIN-keyed open
dataset wired into Command Center Last sale.

## Researched, not viable in-scope

| Source | Finding |
|--------|---------|
| Cook County Recorder of Deeds | No public PIN-keyed API for historical deeds |
| MyDec / transfer declarations | Coverage starts ~2013; does not fill pre-Assessor gaps (e.g. 1993 Redfin) |
| Redfin / commercial scrapers | Not an open-data path; out of scope for this pack |

When Assessor enrichment succeeds with no row, UI shows explicit **No sale found**
copy via `sale_date_meta.status === 'no_sale'` rather than a silent em dash.

## Follow-up

If a future open PIN-keyed deed index appears, wire it beside Assessor in
`resolve_sale_date_meta` / enrichment — do not scrape Redfin for production.
