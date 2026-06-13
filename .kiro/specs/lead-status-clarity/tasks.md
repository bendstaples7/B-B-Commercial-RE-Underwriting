# Implementation Plan: Lead Status Clarity

## Overview

Six targeted changes across three frontend components, one API service method, one Marshmallow schema, and one backend controller. No migrations, no new files required. Tasks are ordered by dependency — backend first, then frontend.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1.1", "1.2"],
      "description": "Backend: schema and controller — foundation for frontend calls"
    },
    {
      "wave": 2,
      "tasks": ["2.1"],
      "description": "Frontend API service — required before component changes call the updated endpoint"
    },
    {
      "wave": 3,
      "tasks": ["3.1", "3.2", "3.3"],
      "description": "Frontend component changes — all can land in parallel once wave 2 is done"
    }
  ]
}
```

## Tasks

### Phase 1: Backend Changes

- [x] 1.1 Add optional `reason` field to `LeadStatusUpdateSchema` in `backend/app/schemas.py`
  - Add `reason = fields.String(load_default=None, validate=validate.Length(max=500))` to the schema
  - Field is optional — existing callers that omit it continue to work without any change
  - _Requirement: 2.4_

- [x] 1.2 Update `update_status` endpoint in `backend/app/controllers/command_center_controller.py` to use `reason`
  - Read `reason = data.get('reason') or ''` from the validated schema output
  - When `reason` is non-empty, build summary as: `f"Status changed from '{old_status}' to '{new_status}'. {reason}"`
  - When `reason` is absent/empty, use existing format: `f"Status changed from '{old_status}' to '{new_status}'."`
  - Store `reason` in `event_metadata` under key `"reason"` (value `None` when absent, string when present)
  - No change to the response shape — endpoint still returns `{'lead_status': ..., 'recommended_action': ...}`
  - _Requirements: 2.5, 2.6_

### Phase 2: Frontend API Service

- [x] 2.1 Update `commandCenterService.updateStatus` in `frontend/src/services/api.ts` to accept and forward optional `reason`
  - Change signature to: `updateStatus: (leadId: number, status: LeadStatus, reason?: string) => ...`
  - Pass `reason: reason || undefined` in the request body so absent reasons are omitted from the JSON payload
  - _Requirement: 2.2_

### Phase 3: Frontend Component Changes

- [x] 3.1 Update `LeadCommandCenter.tsx` — Status display consolidation + inline reason capture
  - **Remove** the `LeadStatusChip` block from the lead header box (the `{data.lead_status && <Box><LeadStatusChip ... /></Box>}` block)
  - **Remove** the notes/status-note block from inside the lead header box
  - **Add** a "Lead Notes" section after the Open Tasks `<Box>` and before the first `<Divider>`. Render only when `data.notes` is non-null and non-empty. Use neutral styling: plain border, no warning background. Label: "Lead Notes".
  - **Add** state variables: `pendingStatus: LeadStatus | null` (init `null`) and `statusReason: string` (init `''`)
  - **Modify** `handleStatusChange`: instead of calling the API, set `setPendingStatus(newStatus)` and `setStatusReason('')`
  - **Add** `handleStatusConfirm`: calls `commandCenterService.updateStatus(leadId, pendingStatus, statusReason.trim() || undefined)`, then invalidates query, then resets `pendingStatus` and `statusReason`
  - **Add** `handleStatusCancel`: resets `pendingStatus` and `statusReason` without any API call
  - **Add** inline confirmation UI inside the lead header box, rendered only when `pendingStatus !== null`. Shows: transition label, optional `TextField` (label "What happened? (optional)", maxLength 500), Confirm + Cancel buttons
  - **Disable** the `<Select>` dropdown when `pendingStatus !== null` OR `statusChanging` is true
  - **Update** `deriveQueueContext`: when `data.has_overdue_hubspot_task` is true, change the task description string to include `(HubSpot task)` after the task title: `` `"${data.overdue_task_title}" (HubSpot task) was due...` ``
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.3, 2.7, 2.8, 3.4_

- [x] 3.2 Update `LeadTimeline.tsx` (or its per-entry rendering sub-component) — HubSpot source badge
  - Identify where individual timeline entries are rendered (the component that maps over entries and renders actor, timestamp, summary)
  - Add an "Imported from HubSpot" `<Chip>` inline on the actor/timestamp line when `entry.source === 'hubspot' || entry.source === 'hubspot_import'`
  - Chip props: `size="small"`, `variant="outlined"`, muted color (`color: 'text.secondary'`, `borderColor: 'divider'`), `fontSize: '0.65rem'`, `height: 18`
  - Native entries (source `'manual'` or `'system'`) receive no badge
  - _Requirements: 3.1, 3.2, 3.5, 3.6_

- [x] 3.3 Update `LeadTaskList.tsx` — HubSpot task label
  - Identify where individual task rows are rendered
  - Add a secondary `<Typography variant="caption" color="text.secondary">` line reading "HubSpot task — complete in HubSpot to close" immediately below the task title when `task.source === 'hubspot'`
  - _Requirements: 3.3_

---

## Notes

- No database migration is required. The only data change is an additive `"reason"` key in the `event_metadata` JSON of new `status_changed` timeline entries.
- The `LeadStatusChip` component itself (`LeadStatusChip.tsx`) is not deleted — it is still used in queue table rows and other list views. Only its usage inside `LeadCommandCenter.tsx` is removed.
- The `lead.notes` DB column, its API field name (`notes`), and all backend code that reads/writes it are unchanged. Only the frontend label and position change.
- Tasks 3.1, 3.2, and 3.3 can be implemented in parallel since they touch different component files.
