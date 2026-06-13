# Requirements Document

## Introduction

The Lead Command Center currently presents conflicting status information across three independent surfaces: the `lead_status` enum dropdown, the `lead.notes` free-text column (mislabeled "Status Note"), and HubSpot-imported timeline entries. These surfaces are not coupled to each other, so they frequently contradict — a lead can simultaneously show `lead_status = mailing_no_contact_made`, a notes field reading "Mailing, contact made, no interest", and a HubSpot timeline entry confirming actual contact was made.

This spec resolves the confusion through three coordinated changes:

1. **Status Display Consolidation** — Remove the redundant `LeadStatusChip` below the dropdown (the dropdown alone is authoritative), rename `lead.notes` from "Status Note" to "Lead Notes", and move it below the fold so it no longer implies a connection to `lead_status`.
2. **Status Change Reason Capture** — When a user changes `lead_status`, prompt for an optional "What happened?" reason. That reason is written into the `status_changed` timeline entry body so context lives attached to the specific transition rather than as a stale free-text field.
3. **HubSpot Source Labeling** — Visually badge all HubSpot-imported timeline entries as "Imported from HubSpot" and label HubSpot tasks in the Open Tasks list as "Complete in HubSpot" so users can distinguish live authoritative state from historical synced records.

---

## Glossary

- **lead_status**: The authoritative enum column on the `leads` table representing the current pipeline stage. Drives queues, the action engine, and recommended action computation.
- **lead.notes**: A free-text column on the `leads` table. Previously mislabeled "Status Note" in the UI. Contains general observations that are not coupled to `lead_status`.
- **status_changed timeline entry**: A `LeadTimelineEntry` with `event_type = 'status_changed'` written whenever `lead_status` is updated via `PATCH /api/leads/<id>/status`.
- **HubSpot-imported entry**: A `LeadTimelineEntry` with `source = 'hubspot'` or `source = 'hubspot_import'`, or a task row with `source = 'hubspot_import'`. These are read-only synced records.
- **native entry**: A `LeadTimelineEntry` with `source = 'manual'` or `source = 'system'`, created within this platform.
- **Open Tasks list**: The section in `LeadCommandCenter` that shows both native `LeadTask` records and HubSpot-sourced tasks from the `tasks` table.

---

## Requirements

### Requirement 1: Status Display Consolidation

**User Story:** As a real estate investor, I want to see exactly one authoritative status indicator on a lead, so that I am never confused by conflicting labels showing different values simultaneously.

#### Acceptance Criteria

1. WHEN the Lead Command Center header renders, THE Platform SHALL display `lead_status` exactly once — as the `<Select>` dropdown. The `LeadStatusChip` colored pill that currently renders immediately below the dropdown SHALL be removed from the header.
2. WHEN `lead.notes` is non-null and non-empty, THE Platform SHALL render it as "Lead Notes" (not "Status Note") in a section below the Open Tasks list, outside the lead header box.
3. THE "Lead Notes" section SHALL use neutral styling (no warning/yellow background) to visually distinguish it from status-bearing UI elements.
4. WHEN `lead.notes` is null or empty, THE Platform SHALL render no "Lead Notes" section (same conditional-render behavior as today).
5. THE `lead_status` dropdown SHALL remain the sole UI control for changing pipeline stage, and its position in the header SHALL not change.

---

### Requirement 2: Status Change Reason Capture

**User Story:** As a real estate investor, I want to record why I changed a lead's status at the moment I change it, so that the timeline always explains the context of each transition rather than having a stale floating note that contradicts the current status.

#### Acceptance Criteria

1. WHEN a user selects a new value from the `lead_status` dropdown AND the new value differs from the current value, THE Platform SHALL display an inline confirmation UI below the dropdown before committing the change. This UI SHALL include:
   - The transition being made (e.g., "Changing status to Mailing, Contact Made, No Interest")
   - An optional free-text field labeled "What happened? (optional)"
   - A "Confirm" button and a "Cancel" button
2. WHEN the user clicks "Confirm", THE Platform SHALL call `PATCH /api/leads/<id>/status` with both the new `status` value and the optional `reason` string.
3. WHEN the user clicks "Cancel", THE Platform SHALL revert the dropdown to its previous value and dismiss the inline UI without making any API call.
4. THE `PATCH /api/leads/<id>/status` endpoint SHALL accept an optional `reason` field (string, max 500 chars) in the request body.
5. WHEN `reason` is provided in the status update request, THE `status_changed` timeline entry written by the endpoint SHALL include the `reason` text in its `summary` field, formatted as: `"Status changed from '{old}' to '{new}'. {reason}"`. WHEN `reason` is absent or empty, the summary SHALL be the existing format: `"Status changed from '{old}' to '{new}'."`.
6. THE `reason` field SHALL be stored in the `status_changed` timeline entry's `event_metadata` JSON under the key `"reason"` for structured access.
7. THE inline confirmation UI SHALL be dismissible without requiring a reason — the reason field is always optional.
8. WHEN a status change is in progress (confirmation UI is open), THE dropdown SHALL visually indicate the pending state and SHALL NOT allow another status change to be initiated until the current one is confirmed or cancelled.

---

### Requirement 3: HubSpot Source Labeling

**User Story:** As a real estate investor, I want to clearly see which timeline entries and tasks came from HubSpot versus were logged natively in this platform, so that I can distinguish current authoritative state from historical imported records.

#### Acceptance Criteria

1. WHEN the Lead Timeline renders an entry with `source = 'hubspot'` or `source = 'hubspot_import'`, THE Platform SHALL display a badge or label on that entry reading "Imported from HubSpot". This label SHALL be visually distinct from the entry body text (e.g., smaller, muted color, or pill style).
2. THE "Imported from HubSpot" badge SHALL appear on every HubSpot-sourced entry regardless of `event_type` (notes, calls, tasks, deal stage changes, etc.).
3. WHEN the Open Tasks list renders a task with `source = 'hubspot'`, THE Platform SHALL display a secondary label beneath the task title reading "HubSpot task — complete in HubSpot to close". This label SHALL use muted/secondary styling.
4. WHEN the Today's Action banner renders for a lead whose `has_overdue_hubspot_task` is `true`, THE Platform SHALL append the text "(HubSpot task)" after the task title in the banner reason string, so it reads e.g.: `"Follow up on 3046 N Hamlin Ave" (HubSpot task) was due 5/15/2026 and is still open.`
5. Native timeline entries (source = 'manual' or source = 'system') SHALL NOT display any source badge, keeping their appearance clean and uncluttered.
6. THE visual treatment for HubSpot entries SHALL not obscure the entry content — the badge SHALL be an additive label, not a replacement for the summary text.

---

## Out of Scope

- Migrating existing `lead.notes` content to timeline entries. The `notes` column retains its existing data; only the label and position in the UI change.
- Adding an edit control for `lead.notes` to the Command Center (it is currently display-only in this view and remains so).
- Changing the `lead_status` enum values or adding new statuses.
- Bi-directional HubSpot task sync (marking a HubSpot task complete from this platform). HubSpot tasks remain read-only.
- Retroactively adding reasons to existing `status_changed` timeline entries.
