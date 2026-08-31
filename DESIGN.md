# DESIGN.md — B&B Real Estate Analyzer (scoped)

> Scoped to **Channel ROI** and Marketing analytics surfaces. Reuses the
> existing MUI theme in `frontend/src/main.tsx` and Mail Batches table density —
> not a product rebrand.

## Intent

Help compare **dollars in → responses out → projected return** across Direct
Mail and Facebook in one Marketing screen, without inventing a new visual
language.

## Tokens (inherit)

- Palette, typography, shape, Paper/Table density: existing app theme +
  `MailCampaignsPanel` header/body cell styles (`0.75rem` dense cells)
- No new display fonts, purple gradients, or dashboard “stat pill” chrome

## Channel ROI layout

1. **One primary title:** `Channel ROI` (no duplicate breadcrumb title at hub)
2. **Rollup row (first):** one split comparison row (Direct Mail | Facebook) —
   not a generic multi-card mosaic — spend, responses, cost per response,
   projected ROI as `N×` when knobs set (FB response rate only when link clicks
   exist)
3. **Breakdowns (second):** MUI **tabs** — Direct mail (default) | Facebook —
   one dense table at a time matching Mail Batches
4. **Admin settings (last):** compact strip — expected profit per deal, assumed
   close rate, Meta ad account + masked token, Save, Refresh, last synced —
   hidden for non-admins
5. **Call log:** optional “Response to Facebook campaign?” alongside mailer
   attribution — same form density

## Empty / error states

- Meta not connected (admin): CTA “Connect Meta ad account”
- Meta not connected (non-admin): “Not connected”
- No mail / FB campaigns: empty table copy with next step
- Projection knobs unset: “Set assumptions” control focusing settings

## Hostile env (metric chrome)

- No glow/halo/pulse on ROI numbers
- Tables `overflow-x: auto`; theme text colors only

## Decisions log

- D1: Match existing Marketing chrome
- D2: Rollup → breakdowns → admin settings
- Review 1A: Tabs (Direct mail default | Facebook)
- Projected ROI as multiplier `N×`
