# Design Document: Lead Status Clarity

## Overview

Three targeted changes to `LeadCommandCenter` and the status update API that eliminate conflicting status signals and clarify the provenance of imported HubSpot data. No new tables, no migrations — all changes are to existing frontend components and one existing backend endpoint.

### Key Design Decisions

**Remove the `LeadStatusChip` from the header, not just hide it.** The chip and the `<Select>` dropdown display identical information. Keeping both forces users to mentally reconcile two identical-looking elements. The dropdown is the actionable control; the chip adds no information and is deleted from the header entirely.

**Rename `lead.notes` in the UI only — no schema change.** The `notes` column stores general observations unrelated to pipeline stage. The only fix needed is the label ("Status Note" → "Lead Notes") and position (moved below Open Tasks, outside the header box). The DB column, API field name, and backend code are unchanged.

**Status change reason as an inline confirmation flow, not a modal.** A modal would interrupt the user's flow when they frequently change status. An inline expansion below the dropdown (similar to a destructive-action confirmation in GitHub) is lighter and keeps context visible. The reason field is always optional so the workflow is never blocked.

**`reason` appended to the existing `status_changed` timeline entry — no new event type.** The `status_changed` entry already exists and captures old/new status. Adding `reason` to its `summary` and `event_metadata` is sufficient and keeps the timeline schema unchanged.

**HubSpot badges as additive labels — no restructuring of timeline rendering.** The existing `LeadTimeline` component renders a list of entries. Each entry gets a small "Imported from HubSpot" pill added when `source` matches. No refactoring of the timeline data structure or pagination is needed.

---

## Architecture

All changes are isolated to:
- `frontend/src/components/LeadCommandCenter.tsx` — display consolidation + inline status change flow
- `frontend/src/components/LeadTimeline.tsx` (or its entry sub-component) — HubSpot badge
- `frontend/src/components/LeadTaskList.tsx` — HubSpot task label
- `backend/app/controllers/command_center_controller.py` — `update_status` endpoint accepts `reason`
- `backend/app/schemas.py` — `LeadStatusUpdateSchema` gains optional `reason` field

No new files, no migrations, no new API endpoints.

---

## Detailed Design

### 1. Status Display Consolidation

#### What changes in `LeadCommandCenter.tsx`

**Remove `LeadStatusChip`** from the header box. The current JSX block:

```tsx
{/* Lead status chip — primary pipeline stage display */}
{data.lead_status && (
  <Box sx={{ mt: 1 }}>
    <LeadStatusChip status={data.lead_status} />
  </Box>
)}
```
...is deleted entirely. The `<Select>` dropdown at the top right of the header already shows the same value with the same label text from `LEAD_STATUS_LABELS`.

**Relocate and rename the Notes box.** The current JSX block inside the header box:
```tsx
{data.notes && (
  <Box sx={{ mt: 1.5, p: 1.5, bgcolor: 'warning.50', ... }}>
    <Typography ... >Status Note</Typography>
    <Typography>{data.notes}</Typography>
  </Box>
)}
```
...is removed from inside the header `<Box>` and re-rendered as a standalone `<Box>` after the Open Tasks section and before the `<Divider>` that precedes Log Note. The label changes to "Lead Notes" and the styling changes from `warning.50` background to no background (plain `Paper` variant or just a `Box` with a light `divider`-colored border). This makes it clearly an informational field, not a status indicator.

#### Visual layout after changes

```
┌─────────────────────────────────────────────┐
│ [Queue banners]                              │
│                                             │
│ ┌── Lead Header ────────────────────────── ┐│
│ │ Manuel Medellin          Lead Score  49.8 ││
│ │ 3046 N Hamlin Ave                         ││
│ │ ✓ Matched — Property Matched   [Status ▾] ││  ← dropdown only, chip gone
│ └───────────────────────────────────────── ┘│
│                                             │
│ [Recommended Action panel]                  │
│ [Open Tasks]                                │
│                                             │
│ ┌── Lead Notes ─────────────────────────── ┐│  ← moved here, neutral style
│ │ Mailing, contact made, no interest        ││
│ └───────────────────────────────────────── ┘│
│                                             │
│ ──────────── divider ───────────────────── │
│ [Log Note]                                  │
│ [Log Call]                                  │
│ [Timeline]                                  │
└─────────────────────────────────────────────┘
```

---

### 2. Status Change Reason Capture

#### Frontend: Inline confirmation flow

When the user selects a new status from the dropdown, instead of immediately calling the API, the component transitions to a "pending confirmation" state:

```
State machine:
  idle → pending_confirm (user picks new status)
  pending_confirm → idle (user cancels)
  pending_confirm → saving (user confirms)
  saving → idle (API responds)
```

New state variables added to `LeadCommandCenter`:
```typescript
const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null)
const [statusReason, setStatusReason] = useState('')
```

The `handleStatusChange` function no longer calls the API directly. Instead it sets `pendingStatus`. The existing confirmation/save logic moves to a new `handleStatusConfirm` function.

The inline confirmation UI renders inside the lead header box, below the dropdown row, only when `pendingStatus !== null`:

```tsx
{pendingStatus && (
  <Box sx={{ mt: 1.5, p: 1.5, border: 1, borderColor: 'primary.200', borderRadius: 1, bgcolor: 'primary.50' }}>
    <Typography variant="body2" sx={{ mb: 1 }}>
      Changing status to <strong>{LEAD_STATUS_LABELS[pendingStatus]}</strong>
    </Typography>
    <TextField
      size="small"
      fullWidth
      multiline
      maxRows={3}
      label="What happened? (optional)"
      value={statusReason}
      onChange={(e) => setStatusReason(e.target.value)}
      inputProps={{ maxLength: 500 }}
      sx={{ mb: 1 }}
    />
    <Stack direction="row" spacing={1}>
      <Button
        size="small"
        variant="contained"
        onClick={handleStatusConfirm}
        disabled={statusChanging}
      >
        {statusChanging ? <CircularProgress size={16} /> : 'Confirm'}
      </Button>
      <Button size="small" variant="outlined" onClick={handleStatusCancel} disabled={statusChanging}>
        Cancel
      </Button>
    </Stack>
  </Box>
)}
```

The `<Select>` dropdown is disabled while `pendingStatus !== null` OR while `statusChanging` is true.

#### Backend: `LeadStatusUpdateSchema` and `update_status` endpoint

`LeadStatusUpdateSchema` in `schemas.py` gains an optional field:
```python
reason = fields.String(load_default=None, validate=validate.Length(max=500))
```

The `update_status` endpoint in `command_center_controller.py` reads `reason` from the validated data and uses it when building the timeline entry summary:

```python
reason = data.get('reason') or ''
if reason:
    summary = f"Status changed from '{old_status}' to '{new_status}'. {reason}"
else:
    summary = f"Status changed from '{old_status}' to '{new_status}'."

entry = LeadTimelineEntry(
    ...
    summary=summary,
    event_metadata={
        'previous_status': old_status,
        'new_status': new_status,
        'reason': reason or None,
    },
)
```

#### API call from frontend

`commandCenterService.updateStatus` in `api.ts` is updated to accept an optional `reason`:
```typescript
updateStatus: (leadId: number, status: LeadStatus, reason?: string) =>
  api.patch(`/leads/${leadId}/status`, { status, reason: reason || undefined })
```

---

### 3. HubSpot Source Labeling

#### Timeline entries

The `LeadTimeline` component (or its per-entry sub-component) receives the `source` field on each entry. A small inline badge is added when `source === 'hubspot' || source === 'hubspot_import'`:

```tsx
{(entry.source === 'hubspot' || entry.source === 'hubspot_import') && (
  <Chip
    label="Imported from HubSpot"
    size="small"
    variant="outlined"
    sx={{ fontSize: '0.65rem', height: 18, color: 'text.secondary', borderColor: 'divider', ml: 1 }}
  />
)}
```

This renders inline next to the entry header (actor + timestamp line), not as a separate row.

#### Open Tasks list — HubSpot task label

In `LeadTaskList.tsx`, tasks with `source === 'hubspot'` get a secondary line below the title:

```tsx
{task.source === 'hubspot' && (
  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
    HubSpot task — complete in HubSpot to close
  </Typography>
)}
```

#### Today's Action banner — HubSpot task annotation

In `LeadCommandCenter.tsx`, the `deriveQueueContext` function builds the `reason` string for the Today's Action banner. When `has_overdue_hubspot_task` is true, the reason string gains a "(HubSpot task)" suffix:

```typescript
const taskDesc = data.overdue_task_title
  ? `"${data.overdue_task_title}" (HubSpot task) was due ${...} and is still open.`
  : 'A HubSpot task is overdue.'
```

---

## Component Change Summary

| File | Change |
|------|--------|
| `LeadCommandCenter.tsx` | Remove `LeadStatusChip` block; relocate notes box with new label/style; add `pendingStatus`/`statusReason` state; inline confirm UI; `deriveQueueContext` HubSpot task annotation |
| `LeadTimeline.tsx` (or entry sub-component) | Add "Imported from HubSpot" badge for `source === 'hubspot'` or `'hubspot_import'` |
| `LeadTaskList.tsx` | Add "HubSpot task — complete in HubSpot to close" label for `source === 'hubspot'` tasks |
| `frontend/src/services/api.ts` | Add optional `reason` param to `commandCenterService.updateStatus` |
| `backend/app/schemas.py` | Add optional `reason` field to `LeadStatusUpdateSchema` |
| `backend/app/controllers/command_center_controller.py` | Use `reason` in timeline entry summary and `event_metadata` |

---

## Data Models

No schema changes. All existing models remain unchanged.

The only data-layer change is to the `event_metadata` JSON written into the `lead_timeline_entries` table by the `update_status` endpoint. The `status_changed` entry's `event_metadata` object gains an optional `"reason"` key:

```json
{
  "previous_status": "mailing_no_contact_made",
  "new_status": "mailing_contacted_no_interest",
  "reason": "Called today, owner said not interested."
}
```

When no reason is provided, `"reason"` is `null`. Existing entries without a `"reason"` key are unaffected — the frontend never reads `reason` from timeline metadata for display purposes.

---

## Components and Interfaces

### Modified Components

#### `LeadCommandCenter.tsx`
- **New state**: `pendingStatus: LeadStatus | null`, `statusReason: string`
- **Modified handler**: `handleStatusChange(newStatus)` — sets `pendingStatus`, does not call API
- **New handlers**: `handleStatusConfirm()`, `handleStatusCancel()`
- **Removed JSX**: `LeadStatusChip` block in header; notes block inside header
- **Added JSX**: Inline confirmation box (conditional on `pendingStatus !== null`); "Lead Notes" section after Open Tasks
- **Modified JSX**: `deriveQueueContext` HubSpot task reason string

#### `LeadTimeline.tsx` (entry renderer)
- **Added JSX**: "Imported from HubSpot" `<Chip>` on entries where `source === 'hubspot' || source === 'hubspot_import'`

#### `LeadTaskList.tsx` (task row renderer)
- **Added JSX**: "HubSpot task — complete in HubSpot to close" caption on tasks where `source === 'hubspot'`

### Modified API Service

#### `frontend/src/services/api.ts` — `commandCenterService.updateStatus`
```typescript
// Before
updateStatus: (leadId: number, status: LeadStatus) =>
  api.patch(`/leads/${leadId}/status`, { status })

// After
updateStatus: (leadId: number, status: LeadStatus, reason?: string) =>
  api.patch(`/leads/${leadId}/status`, { status, reason: reason || undefined })
```

### Modified Backend

#### `backend/app/schemas.py` — `LeadStatusUpdateSchema`
```python
# Added field
reason = fields.String(load_default=None, validate=validate.Length(max=500))
```

#### `backend/app/controllers/command_center_controller.py` — `update_status`
- Reads `reason` from validated data
- Conditionally appends it to the `summary` string
- Stores it in `event_metadata['reason']`

---

## Error Handling

- If `handleStatusConfirm` receives an API error, the existing `statusError` state is set and displayed. `pendingStatus` and `statusReason` are reset so the user can try again or cancel.
- The `reason` field on the backend schema uses `validate.Length(max=500)` — if a client somehow sends a longer string, a 400 validation error is returned with the existing `handle_errors` decorator response format.
- If the backend is unavailable when the user confirms a status change, the confirmation UI remains visible and shows the error, allowing the user to retry or cancel.

---

## Correctness Properties

### Property 1: Status change requires explicit user confirmation
Changing `lead_status` via the dropdown always requires a user Confirm or Cancel action before the API is called — selecting a new value from the dropdown alone never triggers an API call.
**Validates: Requirements 2.1, 2.3, 2.8**

### Property 2: Notes content is immutable
The `lead.notes` DB column content is never read from or written to by this feature — only its UI label ("Lead Notes") and position (below Open Tasks) change.
**Validates: Requirements 1.2, 1.3, 1.4**

### Property 3: HubSpot badges are additive only
HubSpot source badges do not change the text, ordering, or pagination of timeline entries. Every entry that existed before this change renders identically except for the added badge on HubSpot-sourced entries.
**Validates: Requirements 3.1, 3.2, 3.5, 3.6**

### Property 4: Reason is always optional
The `reason` field is always optional at every layer (UI field, API schema, timeline entry). No existing workflow is blocked or changed for users who skip the reason field.
**Validates: Requirements 2.4, 2.7**

---

## Testing Strategy

- **Unit tests (frontend)**: Test that selecting a new status sets `pendingStatus` and does not call `updateStatus` immediately. Test that Confirm calls `updateStatus` with the correct `status` and `reason`. Test that Cancel resets `pendingStatus` without an API call.
- **Integration tests (backend)**: Test `PATCH /api/leads/<id>/status` with and without `reason`. Verify the timeline entry `summary` and `event_metadata` match the expected format in both cases.
- **Visual regression**: Manually verify the lead header shows only one status indicator (dropdown only, no chip) for a lead with a known status.
