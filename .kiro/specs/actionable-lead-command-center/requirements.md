# Requirements Document

## Introduction

The Actionable Lead Command Center transforms the existing real estate deal sourcing platform into the user's primary day-to-day CRM, replacing HubSpot. The platform already holds leads, HubSpot history, property analysis data, and basic scoring — but provides no clear guidance on what to do next with any given lead. This feature closes that gap by making every active lead actionable: each lead must have either a recommended action, an open task, or an intentional parked/suppressed state at all times.

The system introduces two distinct constructs — **recommended actions** (system-generated strategic next-best moves based on deterministic rules) and **tasks** (specific executable work items created by the user or triggered by completing an action). Together they power queue-based workflows, a lead detail command center, a unified activity timeline, and native note/call logging — all oriented around answering the daily question: "What should I work on today?"

---

## Glossary

- **Lead**: A property owner record with property details, contact info, optional skip-trace data, and a computed lead score (0–100).
- **Recommended_Action**: A system-generated, deterministic next-best-move label assigned to a Lead. One of: `enrich_data`, `resolve_match`, `analyze_property`, `follow_up_now`, `ready_for_outreach`, `add_contact_info`, `create_task`, `nurture`, `suppress`, `do_not_contact`.
- **Task**: A specific, user-visible work item attached to a Lead. One of: `call_owner_today`, `research_missing_pin`, `match_hubspot_deal`, `run_property_analysis`, `add_to_mail_batch`, `skip_trace_owner`, or a free-text custom task.
- **Lead_Status**: The current lifecycle state of a Lead. One of: `new`, `active`, `follow_up`, `nurture`, `under_contract`, `closed`, `suppressed`, `do_not_contact`.
- **Queue**: A filtered, prioritized view of Leads grouped by a shared condition (e.g., overdue follow-up, no next action). Queues are the primary navigation surface for daily work.
- **Timeline**: The ordered, append-only log of all activity on a Lead — including HubSpot-imported history, native notes, call logs, task completions, recommended action changes, and status changes.
- **Action_Engine**: The deterministic rule engine that evaluates each Lead's signals and assigns or updates its Recommended_Action.
- **HubSpot_Activity**: A note, call, task, or deal record imported from HubSpot and stored in the platform's Timeline for a Lead.
- **Signal**: A boolean or scalar attribute on a Lead used as input to the Action_Engine (e.g., `has_phone`, `has_property_match`, `analysis_complete`, `follow_up_overdue`, `is_warm`).
- **Command_Center**: The lead detail view that surfaces the Recommended_Action, open Tasks, Timeline, and action buttons for a single Lead.
- **Snooze**: A user action that defers a Task or Recommended_Action until a specified future date without marking it complete.
- **Park**: A user action that places a Lead in the `nurture` status, suppressing it from active queues until a future date or manual re-activation.


---

## Requirements

### Requirement 1: Problem Statement and Goals

**User Story:** As a real estate investor, I want a single platform that tells me what to do next with every lead, so that I can replace HubSpot and stop losing deals to inaction or forgotten follow-ups.

#### Acceptance Criteria

1. THE Platform SHALL ensure that every Lead with a `Lead_Status` of `new`, `active`, or `follow_up` has at least one of the following: a non-null `Recommended_Action`, or at least one open Task (where "open" means status is not `completed` and not `cancelled`).
2. WHEN the user navigates to the primary dashboard, THE Platform SHALL display the count of Leads in each active Queue, where "active Queue" means any Queue whose membership criteria include Leads with `Lead_Status` of `new`, `active`, or `follow_up`.
3. THE Platform SHALL store all HubSpot_Activity records (notes, calls, tasks, deal stage changes) for each imported Lead as Timeline entries with `source` = `hubspot`.
4. WHEN a user views the Lead Timeline, THE Platform SHALL display HubSpot_Activity entries alongside native platform entries in a single unified chronological view.
5. THE Platform SHALL NOT require the user to open HubSpot to view historical notes, calls, tasks, or deal stage changes for any Lead that has been imported via HubSpot sync.

---

### Requirement 2: Recommended Action Model

**User Story:** As a real estate investor, I want the system to tell me the single best next move for each lead, so that I don't have to decide from scratch every time I open a lead.

#### Acceptance Criteria

1. THE Action_Engine SHALL assign exactly one `Recommended_Action` to each Lead at all times; for any Lead whose `Lead_Status` is `suppressed` or `do_not_contact`, the `Recommended_Action` field SHALL be null.
2. THE Action_Engine SHALL use only deterministic rules based on Lead Signals — no machine learning or AI inference.
3. WHEN one or more of a Lead's Signals change — where Lead Signals are the set of stored Lead fields including property details, contact information, skip-trace data, match status, and lead score — THE Action_Engine SHALL recompute the Lead's `Recommended_Action` within 5 seconds of the change being persisted.
4. THE Platform SHALL support the following `Recommended_Action` values: `enrich_data`, `resolve_match`, `analyze_property`, `follow_up_now`, `ready_for_outreach`, `add_contact_info`, `create_task`, `nurture`, `suppress`, `do_not_contact`.
5. WHEN a Lead record is displayed, THE Platform SHALL render the Lead's current `Recommended_Action` as the first visible element in the Lead Command_Center header and in the corresponding Queue row, without requiring the user to scroll.
6. WHEN a user performs the action corresponding to the Lead's current `Recommended_Action` — defined as the user submitting or confirming the associated workflow step for that action type — THE Action_Engine SHALL recompute the Lead's `Recommended_Action` within 5 seconds and record the previous and new `Recommended_Action` values, along with a UTC timestamp, in the Lead Timeline.

---

### Requirement 3: Task Model

**User Story:** As a real estate investor, I want to create and track specific work items for each lead, so that I can execute on the recommended strategy in concrete steps.

#### Acceptance Criteria

1. THE Platform SHALL support the following built-in Task types: `call_owner_today`, `research_missing_pin`, `match_hubspot_deal`, `run_property_analysis`, `add_to_mail_batch`, `skip_trace_owner`.
2. THE Platform SHALL allow the user to create a free-text custom Task for any Lead, with a title of 1–255 characters.
3. WHEN a Task is created, THE Platform SHALL record the Task with a `status` of `open`, a `created_at` UTC timestamp, and an optional `due_date`.
4. WHEN a user marks a Task as complete and the Task `status` is `open`, THE Platform SHALL set the Task `status` to `completed`, record a `completed_at` UTC timestamp, append a `task_completed` entry to the Lead Timeline, and trigger an Action_Engine recomputation for the Lead. IF the Task `status` is already `completed`, the operation SHALL be a no-op.
5. WHEN a user snoozes a Task, THE Platform SHALL set the Task `due_date` to the user-specified future date and retain the Task `status` as `open`. IF the user-specified date is not strictly after the current server date, THE Platform SHALL reject the snooze and display a validation error.
6. WHEN a user opens the Lead Command_Center, THE Platform SHALL display all open Tasks for that Lead ordered by `due_date` ascending, with Tasks having a null `due_date` displayed last.
7. IF a Task's `due_date` is before 23:59 on the current server date and the Task `status` is `open`, THEN THE Platform SHALL mark the Task as overdue and surface the Lead in the Follow-Up Overdue Queue.

---

### Requirement 4: Relationship Between Recommended Actions and Tasks

**User Story:** As a real estate investor, I want recommended actions and tasks to work together without conflicting, so that I always know both the strategy and the specific next step.

#### Acceptance Criteria

1. THE Platform SHALL treat Recommended_Actions and Tasks as independent constructs — a Lead may have both a non-null `Recommended_Action` and one or more open Tasks (status not `completed` or `cancelled`) simultaneously.
2. IF a Lead has one or more open Tasks AND a non-null `Recommended_Action`, THEN THE Platform SHALL display the open Tasks and the `Recommended_Action` in separate, clearly labeled sections of the Command_Center. IF a Lead has open Tasks but no `Recommended_Action`, THE Platform SHALL display only the open Tasks section.
3. IF the `Recommended_Action` is `create_task` AND the Lead has no open Tasks, THEN THE Platform SHALL display an inline call-to-action in the Command_Center prompting the user to create a Task, with a visible "Create Task" button that opens the Task creation form without navigating away.
4. WHEN a user completes a Task whose type is mapped to the current `Recommended_Action` (e.g., completing `run_property_analysis` when `Recommended_Action` is `analyze_property`), THE Action_Engine SHALL recompute the `Recommended_Action` within 2 seconds of Task completion. The mapping between Task types and `Recommended_Action` values SHALL be defined in a static configuration.
5. WHEN the `Recommended_Action` changes for any reason, THE Platform SHALL NOT automatically delete, archive, or modify any existing Tasks on the Lead.


---

### Requirement 5: Lead Status Model

**User Story:** As a real estate investor, I want each lead to have a clear lifecycle status, so that I can understand at a glance where a lead stands in my pipeline.

#### Acceptance Criteria

1. THE Platform SHALL assign each Lead exactly one `Lead_Status` from the following set: `new`, `active`, `follow_up`, `nurture`, `under_contract`, `closed`, `suppressed`, `do_not_contact`.
2. WHEN a Lead is first imported and no existing record for that Lead exists in the Platform, THE Platform SHALL assign it a `Lead_Status` of `new`.
3. WHEN a user logs a note, completes a Task, or manually updates the status of a Lead, AND IF the Lead's current `Lead_Status` is `new`, THEN THE Platform SHALL transition the `Lead_Status` to `active`.
4. WHEN a user marks a Lead as `do_not_contact`, THE Platform SHALL set the `Lead_Status` to `do_not_contact`, set `Recommended_Action` to null, and remove the Lead from all active Queues.
5. WHEN a user parks a Lead, THE Platform SHALL set the `Lead_Status` to `nurture` and record the park action in the Lead Timeline with an optional re-activation date. IF a re-activation date is provided, it SHALL be a future calendar date no more than 365 days from the park date.
6. WHILE a Lead has a `Lead_Status` of `nurture`, THE Platform SHALL exclude the Lead from the Previously Warm, Follow-Up Overdue, and No Next Action Queues.
7. WHILE a Lead has a `Lead_Status` of `suppressed` or `do_not_contact`, THE Platform SHALL exclude the Lead from all active work Queues.
8. THE Platform SHALL record every `Lead_Status` transition in the Lead Timeline with a UTC timestamp and the actor, where actor is the authenticated user's identifier for user-initiated transitions or the string "System" for platform-initiated transitions.
9. WHEN a user sets a Lead's `Lead_Status` to `suppressed`, THE Platform SHALL set `Recommended_Action` to null and remove the Lead from all active work Queues.
10. WHEN a Lead is re-imported and a record for that Lead already exists in the Platform, THE Platform SHALL preserve the existing `Lead_Status` and NOT reset it to `new`.
11. THE `do_not_contact` status SHALL be permanent unless explicitly overridden by the user via the "Reactivate" action. The `suppressed` status MAY be reversed by the user at any time by changing the `Lead_Status` to `active`.

---

### Requirement 6: Queue Definitions

**User Story:** As a real estate investor, I want my leads organized into actionable queues, so that I can work through them systematically without manually filtering.

#### Acceptance Criteria

1. THE Platform SHALL provide the following Queues in the sidebar navigation: **Today's Action Queue**, **Previously Warm**, **Follow-Up Overdue**, **No Next Action**, **Needs Review**, **Do Not Contact**, **Missing Property Match**.
2. WHEN a Lead's state changes, THE Platform SHALL update the count of Leads displayed next to each Queue name in the sidebar within 5 seconds of the state change being persisted.
3. THE Today's_Action_Queue SHALL contain all Leads where: `Lead_Status` is `active` or `follow_up`, AND (`Recommended_Action` is `follow_up_now` OR any open Task has a `due_date` of today or earlier, anchored to the server's configured timezone).
4. THE Previously_Warm_Queue SHALL contain all Leads where: HubSpot_Activity records exist indicating prior engagement (call, meeting, or deal stage advancement), AND `Lead_Status` is `active` or `new`, AND no Platform_Contact_Event (a Task marked complete with contact type, or a manually logged contact note) has been recorded in the past 90 days.
5. THE Follow_Up_Overdue_Queue SHALL contain all Leads where: (at least one open Task has a `due_date` in the past) OR (`Recommended_Action` is `follow_up_now` AND the last contact date is more than 7 days in the past).
6. THE No_Next_Action_Queue SHALL contain all Leads where: `Lead_Status` is `active` or `new`, AND `Recommended_Action` is null or `create_task`, AND no open Tasks exist.
7. THE Needs_Review_Queue SHALL contain all Leads where: a property analysis has completed and the user has not navigated to the analysis results page since completion, OR a HubSpot sync has added new activity and the user has not dismissed the new-activity notification since that sync, OR the Action_Engine has set a `review_required` flag on the Lead (cleared when the user opens the Command_Center).
8. THE Do_Not_Contact_Queue SHALL contain all Leads where `Lead_Status` is `do_not_contact`.
9. THE Missing_Property_Match_Queue SHALL contain all Leads where no property record has been matched or linked to the Lead.
10. WHEN a Lead's state changes such that it no longer meets a Queue's criteria, THE Platform SHALL remove the Lead from that Queue within 5 seconds. WHEN a Lead's state changes such that it newly meets a Queue's criteria, THE Platform SHALL add the Lead to that Queue within 5 seconds.
11. A Lead MAY appear in multiple Queues simultaneously when it satisfies the membership criteria of more than one Queue. This is expected behavior and SHALL NOT be treated as a data error.

---

### Requirement 7: Lead Detail Command Center

**User Story:** As a real estate investor, I want a single lead detail view that shows me everything I need to act on a lead, so that I don't have to navigate multiple screens to make a decision.

#### Acceptance Criteria

1. THE Command_Center SHALL display the following sections for each Lead: Lead header (name, address, lead score, status badge), Recommended_Action panel, open Tasks list, Timeline, and a quick-action toolbar.
2. THE Command_Center SHALL display the current `Recommended_Action` with a human-readable label, an explanation of why the action was recommended (≤ 280 characters), and 1–5 action buttons to execute or dismiss it.
3. WHEN a user clicks an action button in the Recommended_Action panel and the action succeeds, THE Platform SHALL execute the associated action, record it in the Timeline, and recompute the `Recommended_Action`.
4. IF an action button execution fails, THE Platform SHALL display an inline error message in the Recommended_Action panel and leave the Timeline and `Recommended_Action` unchanged.
5. THE Command_Center SHALL allow the user to create a new Task directly from the open Tasks section. The Task creation form SHALL accept a title (1–255 characters) and an optional due date. Upon successful save, the Tasks list SHALL update without a full page reload.
6. IF Task creation fails (e.g., validation error or server error), THE Platform SHALL display an inline error message and preserve the form data so the user can correct and resubmit.
7. THE Command_Center SHALL display the Lead's `Lead_Status` as an editable badge. Clicking the badge SHALL open a dropdown containing all valid `Lead_Status` values defined in the system.
8. WHEN a user selects a new `Lead_Status` from the dropdown, THE Platform SHALL persist the change, record it in the Timeline, and trigger an Action_Engine recomputation.
9. IF a `Lead_Status` change fails, THE Platform SHALL display an error message and revert the badge to the previous value.
10. IF the Lead has a confirmed property match, THE Platform SHALL display "Matched" in the property match section with a link to the property analysis. IF the Lead has no property match, THE Platform SHALL display "Unmatched" with a link to the Missing Property Match workflow.
11. IF a property analysis exists for the Lead's matched property, THE Platform SHALL display a link to that analysis in the Command_Center.
12. THE Command_Center SHALL be accessible via a direct URL route (`/leads/:id/command-center`) and from any Queue row by clicking the lead name.


---

### Requirement 8: Timeline and Activity Log

**User Story:** As a real estate investor, I want a complete, chronological history of every interaction with a lead — from HubSpot and from the platform — so that I never lose context when picking up a lead.

#### Acceptance Criteria

1. THE Timeline SHALL display all activity for a Lead in reverse-chronological order (newest first), with each entry showing: event type, UTC timestamp, actor (user name or "System" or "HubSpot"), and a summary of up to 500 characters.
2. THE Timeline SHALL include the following event types: `note_added`, `call_logged`, `task_created`, `task_completed`, `task_snoozed`, `recommended_action_changed`, `status_changed`, `hubspot_note`, `hubspot_call`, `hubspot_task`, `hubspot_deal_stage`, `property_analysis_completed`, `lead_imported`.
3. WHEN a HubSpot sync runs, THE Platform SHALL import HubSpot_Activity records (notes, calls, tasks, deal stage changes) for each Lead and store them as Timeline entries with `source` = `hubspot`, using the HubSpot activity's unique ID as the deduplication key.
4. WHEN a HubSpot sync runs, THE Platform SHALL append only HubSpot_Activity records whose HubSpot activity ID is not already present in the Timeline for that Lead — it SHALL NOT create duplicate entries.
5. IF a HubSpot sync fails mid-import for a Lead, THE Platform SHALL retain all Timeline entries already written for that Lead and surface the Lead in the Needs_Review_Queue with reason "HubSpot sync error".
6. THE Timeline SHALL be paginated, displaying 25 entries per page, with a "Load more" control.
7. THE Timeline SHALL be read-only for HubSpot-sourced entries (`source` = `hubspot`). For native entries, only the summary field is editable; event type, UTC timestamp, and actor are locked.
8. WHEN a native Timeline entry (note or call log) is deleted, THE Platform SHALL replace the summary content with "[deleted]" and retain the entry's event type, UTC timestamp, and actor for audit purposes.

---

### Requirement 9: Native Note and Call Logging

**User Story:** As a real estate investor, I want to log notes and call outcomes directly in the platform, so that I don't need to switch to HubSpot to record what happened.

#### Acceptance Criteria

1. THE Platform SHALL provide a "Log Note" action in the Command_Center that accepts free-text input of up to 5,000 characters. WHEN the user clicks the save button, THE Platform SHALL append a `note_added` entry to the Lead Timeline. IF the input is empty or exceeds 5,000 characters, THE Platform SHALL display a validation error and not save.
2. THE Platform SHALL provide a "Log Call" action in the Command_Center that accepts: call outcome (one of `answered`, `voicemail`, `no_answer`, `busy`, `wrong_number`), call duration in minutes (optional, 1–999), and free-text notes of up to 2,000 characters. WHEN the user clicks the save button, THE Platform SHALL persist the call log. IF the outcome field is empty or duration is outside the valid range, THE Platform SHALL display a validation error and not save.
3. WHEN a call is logged with outcome `answered`, THE Platform SHALL update the Lead's `last_contact_date` Signal to the current server date and trigger an Action_Engine recomputation.
4. WHEN a call is logged with outcome `voicemail` or `no_answer`, THE Platform SHALL increment the Lead's `unanswered_call_count` Signal by 1 and trigger an Action_Engine recomputation.
5. WHEN a call is logged with outcome `wrong_number`, THE Platform SHALL set the Lead's `has_phone` Signal to `false`, set the `Recommended_Action` to `add_contact_info`, and trigger an Action_Engine recomputation.
6. WHEN a call is logged, THE Platform SHALL append a `call_logged` entry to the Lead Timeline with the outcome, duration, notes, and UTC timestamp.
7. THE Platform SHALL display a "Log Note" and "Log Call" button in every Queue row. WHEN a user clicks either button from a Queue row, THE Platform SHALL open the same Log Note or Log Call form as in the Command_Center — not a simplified variant — and save the entry to the same Timeline.
8. IF a Log Note or Log Call save operation fails due to a server error, THE Platform SHALL display an error message and preserve the form data so the user can retry without re-entering content.
9. WHEN a Log Note or Log Call is saved from a Queue row, THE Platform SHALL update the Queue row in place within 2 seconds to reflect the new Timeline entry, without a full page reload.

---

### Requirement 10: Previously Warm Queue Workflow

**User Story:** As a real estate investor, I want to see all leads that were previously engaged in HubSpot but have gone cold, so that I can re-engage them systematically.

#### Acceptance Criteria

1. THE Previously_Warm_Queue SHALL display Leads sorted by most recent HubSpot engagement date descending (most recently warm first). IF a Lead has no HubSpot engagement date, it SHALL be sorted last.
2. IF a Lead is in the Previously_Warm_Queue AND no Platform_Contact_Event has been recorded for that Lead in the past 90 days, THEN THE Action_Engine SHALL assign it a `Recommended_Action` of `follow_up_now`.
3. THE Previously_Warm_Queue row SHALL display: lead name, address, last HubSpot activity type, last HubSpot activity date (or "No date available" if absent), current `Recommended_Action`, and action buttons for "Log Call", "Log Note", and "Create Task".
4. WHEN a user logs a call or note from the Previously_Warm_Queue row, THE Platform SHALL update the Lead's Timeline and trigger an Action_Engine recomputation. IF the recomputation results in the Lead no longer meeting the Previously_Warm_Queue membership criteria, THE Platform SHALL remove the Lead from the Queue within 5 seconds.
5. WHEN a user clicks "Suppress" on a Previously_Warm_Queue row, THE Platform SHALL display a confirmation dialog. IF the user confirms, THE Platform SHALL set the Lead's `Lead_Status` to `suppressed` and remove the Lead from the Queue. IF the user cancels, no state changes SHALL occur.
6. THE Previously_Warm_Queue SHALL contain all Leads where: HubSpot_Activity records exist indicating prior engagement (call, meeting, or deal stage advancement), AND `Lead_Status` is `active` or `new`, AND no Platform_Contact_Event has been recorded in the past 90 days.
7. IF the "Suppress" action fails due to a server error, THE Platform SHALL display an error message and leave the Lead's `Lead_Status` unchanged.

---

### Requirement 11: Follow-Up Overdue Queue Workflow

**User Story:** As a real estate investor, I want to see all leads with overdue follow-up tasks or missed follow-up dates, so that I can address them before they go cold.

#### Acceptance Criteria

1. THE Follow_Up_Overdue_Queue SHALL contain all Leads where: (at least one open Task has a `due_date` before the current server date) OR (the Lead has a `follow_up_date` before the current server date AND no open Task exists). Leads SHALL be sorted by the earliest overdue date ascending (most overdue at top), where the sort key is the earliest overdue Task `due_date` or `follow_up_date`.
2. THE Follow_Up_Overdue_Queue row SHALL display: lead name, address, overdue Task description (if an overdue Task exists) or overdue follow-up date (if no overdue Task exists), days overdue, current `Recommended_Action`, and action buttons for "Complete Task", "Snooze", "Log Call", and "Log Note".
3. WHEN a user clicks "Complete Task" on a Follow_Up_Overdue_Queue row, THE Platform SHALL mark the Task as complete, record a `task_completed` Timeline entry including the task description, completion UTC timestamp, and acting user, and trigger an Action_Engine recomputation.
4. WHEN a user clicks "Snooze" on a Follow_Up_Overdue_Queue row, THE Platform SHALL display a date picker. WHEN the user selects a date that is at least 1 calendar day after the current server date and confirms, THE Platform SHALL set the Task `due_date` to the selected date and remove the Lead from the Queue until that date arrives.
5. IF the user dismisses the snooze date picker without selecting a date, THE Platform SHALL leave the Task `due_date` unchanged and keep the Lead in the Queue.
6. IF a Lead has been in the Follow_Up_Overdue_Queue for more than 30 days, THEN on its next scheduled Action_Engine recomputation, THE Action_Engine SHALL change the `Recommended_Action` to `nurture`, set the `review_required` flag to `true`, and remove the Lead from the Follow_Up_Overdue_Queue.


---

### Requirement 12: No Next Action Queue Workflow

**User Story:** As a real estate investor, I want to see all active leads that have no recommended action and no open tasks, so that I can clean them up and ensure nothing falls through the cracks.

#### Acceptance Criteria

1. THE No_Next_Action_Queue SHALL contain all Leads where: `Lead_Status` is `active` or `new`, AND `Recommended_Action` is null or `create_task`, AND no open Tasks exist (where "open" means status is not `completed` or `cancelled`). Leads SHALL be sorted by `Lead_Status` (`new` before `active`) then by lead score descending.
2. THE No_Next_Action_Queue row SHALL display: lead name, address, lead score, `Lead_Status`, days since last activity (defined as calendar days since the most recent task completion, note log, or `Lead_Status` change), and action buttons for "Create Task", "Log Note", "Park", and "Suppress".
3. WHEN a user clicks "Create Task" from the No_Next_Action_Queue row, THE Platform SHALL open an inline Task creation form. WHEN the user saves the Task successfully, THE Platform SHALL remove the Lead from the Queue. IF the Task save fails, THE Platform SHALL display an inline error message and preserve the form data.
4. WHEN a user clicks "Log Note" from the No_Next_Action_Queue row, THE Platform SHALL open the same Log Note form as in the Command_Center. WHEN the note is saved, THE Platform SHALL append a `note_added` Timeline entry and trigger an Action_Engine recomputation.
5. WHEN a user clicks "Park" from the No_Next_Action_Queue row, THE Platform SHALL prompt for an optional re-activation date. IF a re-activation date is provided, it SHALL be a future calendar date. WHEN the user confirms, THE Platform SHALL set the Lead's `Lead_Status` to `nurture` and remove the Lead from the Queue.
6. WHEN a user clicks "Suppress" from the No_Next_Action_Queue row, THE Platform SHALL display a confirmation dialog. IF the user confirms, THE Platform SHALL set the Lead's `Lead_Status` to `suppressed` and remove the Lead from the Queue. IF the user cancels, no state changes SHALL occur.
7. WHEN a Lead's state changes such that it enters or exits the No_Next_Action_Queue, THE Platform SHALL update the sidebar badge count within 5 seconds.

---

### Requirement 13: Needs Review Queue Workflow

**User Story:** As a real estate investor, I want to see all leads that require my attention due to new data or completed analysis, so that I can review and decide on next steps.

#### Acceptance Criteria

1. THE Needs_Review_Queue SHALL display Leads sorted by the date the review trigger occurred, most recent first. IF two Leads have the same trigger date, they SHALL be sorted alphabetically by lead name.
2. THE Needs_Review_Queue row SHALL display: lead name, address, reason for review, date of trigger, and a context-specific action button: "View Analysis" for reason "Property analysis complete", and "View Activity" for reason "New HubSpot activity".
3. WHEN a property analysis completes for a Lead, THE Platform SHALL add the Lead to the Needs_Review_Queue with reason "Property analysis complete" and record the trigger date as the analysis completion UTC timestamp.
4. IF the Lead's current `Recommended_Action` is not already set, THEN THE Platform SHALL set it to `analyze_property` when the property analysis completion trigger fires.
5. WHEN a HubSpot sync adds new activity to a Lead, THE Platform SHALL add the Lead to the Needs_Review_Queue with reason "New HubSpot activity", where "viewed" is defined as the user having opened the Command_Center for that Lead after the sync completed.
6. IF the same review reason is triggered again for a Lead already in the Needs_Review_Queue for that reason, THE Platform SHALL update the existing entry's trigger date to the new event's timestamp rather than creating a duplicate entry.
7. WHEN a user opens the Command_Center for a Lead in the Needs_Review_Queue, THE Platform SHALL mark all review triggers for that Lead as acknowledged and remove the Lead from the Queue if no unacknowledged triggers remain.

---

### Requirement 14: Do Not Contact Handling

**User Story:** As a real estate investor, I want to mark leads as Do Not Contact and have the system enforce that status, so that I never accidentally reach out to someone who has asked not to be contacted.

#### Acceptance Criteria

1. THE Platform SHALL provide a "Do Not Contact" action that is visible without additional navigation from the Command_Center, any Queue row, and the lead list view.
2. WHEN a user initiates the "Do Not Contact" action, THE Platform SHALL display a confirmation dialog stating: "This will close all open tasks and remove this lead from all active queues. This action can be reversed." WHEN the user confirms, THE Platform SHALL set `Lead_Status` to `do_not_contact`, set `Recommended_Action` to null, set all open Tasks to `cancelled` status, remove the Lead from all active work Queues, and append a `status_changed` Timeline entry recording the previous status, new status, and UTC timestamp. IF the user dismisses the dialog, no state changes SHALL occur.
3. THE Do_Not_Contact_Queue SHALL display all Leads with `Lead_Status` = `do_not_contact`, including the date the status was set and the actor who set it.
4. THE Do_Not_Contact_Queue SHALL display a "Reactivate" button for each Lead. WHEN a user clicks "Reactivate", THE Platform SHALL set the `Lead_Status` to `active` and trigger an Action_Engine recomputation. WHEN the recomputation completes, THE Platform SHALL display the updated `Recommended_Action` in the Command_Center.
5. WHILE a Lead has `Lead_Status` of `do_not_contact`, THE Platform SHALL display a "DO NOT CONTACT" badge in a high-contrast color in the Command_Center header and in all Queue rows where the Lead appears, and SHALL disable all outreach action buttons (Log Call, Log Note, and any contact-initiating actions) for that Lead.

---

### Requirement 15: Missing Property Match Workflow

**User Story:** As a real estate investor, I want to see all leads without a matched property record and resolve them quickly, so that I can run property analysis on every viable lead.

#### Acceptance Criteria

1. THE Missing_Property_Match_Queue SHALL display Leads sorted by lead score descending (highest priority unmatched leads first).
2. THE Missing_Property_Match_Queue row SHALL display: lead name, address as entered, lead score, and action buttons for "Search Property", "Research PIN", and "Suppress".
3. WHEN a user clicks "Search Property" from the Missing_Property_Match_Queue row, THE Platform SHALL open the property match search interface pre-populated with the Lead's address.
4. WHEN a property match is confirmed for a Lead, THE Platform SHALL update the Lead's `has_property_match` Signal to `true` and trigger an Action_Engine recomputation. IF the recomputation succeeds, THE Platform SHALL remove the Lead from the Missing_Property_Match_Queue.
5. IF the Action_Engine recomputation fails after a property match is confirmed, THE Platform SHALL display an error message and retain the Lead in the Queue until the next successful recomputation.
6. WHEN a user clicks "Research PIN" from the Missing_Property_Match_Queue row, THE Platform SHALL create a `research_missing_pin` Task for the Lead. WHEN the Task is successfully created, THE Platform SHALL remove the Lead from the Missing_Property_Match_Queue. The removal is permanent — the Lead SHALL NOT re-enter the Queue unless the Task is deleted and no property match exists.
7. WHEN a user clicks "Suppress" from the Missing_Property_Match_Queue row, THE Platform SHALL display a confirmation dialog. IF the user confirms, THE Platform SHALL set the Lead's `Lead_Status` to `suppressed` and remove the Lead from the Queue. IF the user cancels, no state changes SHALL occur.
8. WHEN a Lead enters the Missing_Property_Match_Queue, THE Action_Engine SHALL assign `Recommended_Action` of `resolve_match` to that Lead.


---

### Requirement 16: Recommended Action Engine Logic (Deterministic Rules)

**User Story:** As a real estate investor, I want the system to apply consistent, predictable rules to determine the next best action for each lead, so that I can trust the recommendations without second-guessing them.

#### Acceptance Criteria

1. THE Action_Engine SHALL evaluate rules in the following priority order, assigning the first matching `Recommended_Action`. "No Recommended_Action" means `Recommended_Action = null`. "Open Tasks" means Tasks with status other than `completed` or `cancelled`.
   - Priority 1: IF `Lead_Status` is `do_not_contact`, THEN assign `Recommended_Action = null`.
   - Priority 2: IF `Lead_Status` is `suppressed` or `nurture`, THEN assign `Recommended_Action = null`.
   - Priority 3: IF `has_phone` is `false` AND `has_email` is `false`, THEN assign `add_contact_info`.
   - Priority 4: IF `has_property_match` is `false`, THEN assign `resolve_match`.
   - Priority 5: IF `has_property_match` is `true` AND `analysis_complete` is `false`, THEN assign `analyze_property`.
   - Priority 6: IF `follow_up_overdue` is `true` (last contact date > 7 days ago AND `Lead_Status` is `follow_up`), THEN assign `follow_up_now`.
   - Priority 7: IF `is_warm` is `true` (at least one HubSpot engagement record with a timestamp within the last 90 days exists AND no Platform_Contact_Event has been recorded in the past 90 days), THEN assign `follow_up_now`.
   - Priority 8: IF `analysis_complete` is `true` AND `lead_score` >= 70 AND no open Tasks exist, THEN assign `ready_for_outreach`.
   - Priority 9: IF `data_completeness_score` < 50, THEN assign `enrich_data`.
   - Priority 10: IF no open Tasks exist AND `Lead_Status` is `active` or `new`, THEN assign `create_task`.
   - Priority 11 (default): assign `nurture`.

2. THE Action_Engine SHALL expose a `/api/leads/:id/recommended-action` endpoint that returns the current `Recommended_Action` and the list of Signal field names and their evaluated boolean values that matched the winning rule.
3. THE Action_Engine SHALL be invokable as a Celery task for bulk recomputation across all Leads regardless of `Lead_Status` (the priority rules handle suppression internally).
4. WHEN the Action_Engine runs in bulk, THE Platform SHALL process all Leads within 60 seconds for a dataset of up to 10,000 Leads.
5. THE Action_Engine SHALL record a `recommended_action_changed` Timeline entry only when the `Recommended_Action` value changes — not on every recomputation. The entry SHALL record the previous value, the new value, and the UTC timestamp of the change.

---

### Requirement 17: Queue Row UI Requirements

**User Story:** As a real estate investor, I want each queue row to show me the key information and let me take action without opening the full lead detail, so that I can work through queues efficiently.

#### Acceptance Criteria

1. THE Platform SHALL display each Queue as a table with sortable columns. The following columns SHALL be sortable: lead name, lead score, `Lead_Status`, and property address.
2. EACH Queue row SHALL include: lead name (linked to Command_Center), property address, lead score badge, `Lead_Status` badge, current `Recommended_Action` chip, and a set of action buttons determined by the Lead's current `Lead_Status` and `Recommended_Action` values.
3. THE Platform SHALL render action buttons in each Queue row as icon buttons with tooltips that appear on hover, fitting within the row without horizontal scrolling on a 1280px-wide viewport.
4. WHEN a user takes an action from a Queue row, THE Platform SHALL update the row in place within 2 seconds without a full page reload, using optimistic UI updates.
5. IF an optimistic UI update fails (server returns an error), THE Platform SHALL revert the row to its previous state and display an inline error message.
6. THE Platform SHALL support bulk selection in each Queue, allowing the user to select multiple Leads and apply a single action (e.g., "Suppress all selected", "Create task for all selected").
7. IF a bulk action partially fails (some Leads succeed, some fail), THE Platform SHALL display a summary showing the count of successful and failed updates without reverting the successful updates.
8. THE Platform SHALL display a "No leads in this queue" empty state with an explanation of 20 words or fewer when a Queue contains zero Leads.

---

### Requirement 18: Today's Action Queue (Primary Dashboard)

**User Story:** As a real estate investor, I want a single "Today's Action Queue" that shows me exactly what needs attention today, so that I can start my day with a clear, prioritized list.

#### Acceptance Criteria

1. THE Today's_Action_Queue SHALL be the default landing page after login, accessible at the `/` route.
2. THE Today's_Action_Queue SHALL display Leads in three mutually exclusive sort groups: (1) Leads with at least one open Task whose `due_date` is before the current server date, sorted by the earliest overdue Task `due_date` ascending (most overdue first); (2) Leads with `Recommended_Action` = `follow_up_now` and no overdue Tasks, sorted by lead score descending; (3) all other Leads in the queue, sorted by lead score descending. A Lead SHALL appear in exactly one group.
3. THE Today's_Action_Queue SHALL display a summary header showing: total Leads in queue, count with overdue Tasks, and count with `Recommended_Action` = `follow_up_now`.
4. WHEN the Today's_Action_Queue is empty, THE Platform SHALL display a "You're all caught up" message with a count of total active Leads (where "active" means `Lead_Status` not in `closed`, `suppressed`, or `do_not_contact`) and a link to the No_Next_Action_Queue.
5. WHILE the Today's_Action_Queue page is open, THE Platform SHALL silently refresh the queue data every 60 seconds, updating the displayed list without a full page reload and without resetting the user's scroll position.


---

### Requirement 19: HubSpot History Integration in Timeline

**User Story:** As a real estate investor, I want all my HubSpot history to appear in the platform timeline, so that I have full context on every lead without switching tools.

#### Acceptance Criteria

1. WHEN a HubSpot sync runs, THE Platform SHALL import the following HubSpot record types per Lead: notes, calls (with outcome and duration), tasks (with completion status), and deal stage changes.
2. WHEN HubSpot records are imported, THE Platform SHALL map them to Timeline entries with `source` = `hubspot`, preserving the original HubSpot timestamp.
3. WHEN a Lead's Timeline is displayed, THE Platform SHALL render HubSpot Timeline entries with a HubSpot logo icon to differentiate them from native platform entries.
4. WHEN a HubSpot sync imports call records for a Lead, THE Platform SHALL evaluate the `is_warm` Signal: IF at least one HubSpot call record with outcome `connected` has a timestamp within the past 180 days, THEN `is_warm` SHALL be `true`. IF no such record exists, THEN `is_warm` SHALL be `false`.
5. WHEN HubSpot deal stage records are imported for a Lead, THE Platform SHALL set the Lead's `hubspot_deal_stage` field to the most recent deal stage value by HubSpot timestamp.
6. WHEN a HubSpot sync completes, THE Platform SHALL update the `last_hubspot_sync_at` timestamp on each Lead for which at least one new Timeline entry was written. THE Platform SHALL then trigger Action_Engine recomputation for each Lead whose Signals changed as a result of the sync.
7. WHEN a HubSpot sync runs, THE Platform SHALL not create duplicate Timeline entries for HubSpot records already present, using the HubSpot activity ID as the deduplication key.

---

### Requirement 20: Non-Goals (Explicit Out-of-Scope for MVP)

**User Story:** As a development team, I want a clear list of what is NOT in scope for this MVP, so that we don't build features that aren't needed yet.

#### Acceptance Criteria

1. THE Platform SHALL NOT implement marketing automation or automated outreach sequences in this MVP. "Automated outreach" is defined as any system-initiated contact with a lead that occurs without a per-record user action.
2. THE Platform SHALL NOT integrate with OpenLetterMarketing in this MVP.
3. THE Platform SHALL NOT integrate with skip tracing services in this MVP. The `skip_trace_owner` Task type SHALL display "manual action required" in the UI and SHALL NOT make any external service call.
4. THE Platform SHALL NOT import Chicago public records data in this MVP.
5. THE Platform SHALL NOT use AI, machine learning, or any probabilistic inference for any `Recommended_Action` computation in this MVP.
6. THE Action_Engine SHALL use only deterministic rules such that identical Lead Signal inputs always produce identical `Recommended_Action` outputs with no dependency on external models or stochastic processes.

---

### Requirement 21: Acceptance Criteria — Data Integrity

**User Story:** As a real estate investor, I want the platform to maintain consistent lead data, so that I can trust the information I see.

#### Acceptance Criteria

1. WHEN a Lead's Signal changes, THE Platform SHALL ensure the Lead's `Recommended_Action` is updated to the value that the Action_Engine produces for the Lead's current Signals within 5 seconds of the change being persisted.
2. THE Platform SHALL ensure that a Lead cannot simultaneously have `Lead_Status` of `do_not_contact` and a non-null `Recommended_Action`.
3. THE Platform SHALL ensure that a Lead cannot appear in both the Do_Not_Contact_Queue and any active work Queue (Previously Warm, Follow-Up Overdue, No Next Action, Needs Review, Today's Action Queue) at the same time.
4. THE Platform SHALL ensure that Timeline entries are append-only — no entry may be deleted in a way that removes it from the audit trail (soft-delete with "[deleted]" replacement only).
5. THE Platform SHALL ensure that Task `status` transitions are valid: `open` → `completed` or `open` → `snoozed` (which remains `open` with updated `due_date`). A `completed` Task SHALL NOT be re-opened.
6. IF a user or system attempts an invalid Task `status` transition (e.g., re-opening a `completed` Task), THE Platform SHALL reject the attempt with a 400-level error and leave the Task `status` unchanged.
7. FOR ALL Leads with `Lead_Status` in (`active`, `follow_up`, `new`), THE Platform SHALL ensure that at least one of the following is true: `Recommended_Action` is non-null, OR at least one open Task exists.

---

### Requirement 22: Edge Cases

**User Story:** As a real estate investor, I want the platform to handle unusual lead states gracefully, so that edge cases don't create confusion or data inconsistency.

#### Acceptance Criteria

1. IF a Lead has no address and no property match, THEN THE Action_Engine SHALL assign `Recommended_Action` of `enrich_data` rather than `resolve_match`.
2. IF a HubSpot sync fails for a specific Lead, THEN THE Platform SHALL log the failure, retain the Lead's existing Timeline entries, and surface the Lead in the Needs_Review_Queue with reason "HubSpot sync error".
3. IF a scoring weights update changes the lead score for one or more Leads, THEN THE Action_Engine SHALL recompute the `Recommended_Action` for each affected Lead within 5 seconds of the score change being persisted.
4. IF a user attempts to log a call on a Lead with `Lead_Status` of `do_not_contact`, THEN THE Platform SHALL display an error message indicating the lead is marked Do Not Contact and SHALL NOT save the call log entry.
5. IF a Task's `due_date` is set to a date before the current server date during creation, THEN THE Platform SHALL display a warning but SHALL allow the Task to be saved.
6. IF a Lead satisfies the membership criteria of multiple Queues simultaneously, THE Platform SHALL display that Lead in each applicable Queue. THE Platform SHALL NOT display that Lead more than once within any single Queue.
7. WHEN a bulk Action_Engine recomputation is running, THE Platform SHALL continue to serve read requests for individual Lead `Recommended_Action` values using the last computed value. IF no `Recommended_Action` has ever been computed for a Lead, THE Platform SHALL return null for that Lead's `Recommended_Action` until the recomputation completes.


---

### Requirement 23: Phased Implementation Plan

**User Story:** As a development team, I want a phased implementation plan, so that we can deliver value incrementally and validate each phase before building the next.

#### Acceptance Criteria

1. WHEN the project begins, THE Platform SHALL implement Phase 1 (Data Model Foundation) as the first deliverable, including: Lead Signal fields, `Recommended_Action` field, `Lead_Status` enum expansion, Task model, and Timeline model with HubSpot entry support. Phase 1 is complete when all listed components are reachable via the Platform's API and return valid responses.
2. WHEN Phase 1 acceptance criteria are met, THE Platform SHALL implement Phase 2 (Action Engine) as the second deliverable, including: the deterministic rule engine, the `/api/leads/:id/recommended-action` endpoint, and the Celery bulk recomputation task. Phase 2 is complete when all listed components are reachable via the Platform's API and return valid responses.
3. WHEN Phase 2 acceptance criteria are met, THE Platform SHALL implement Phase 3 (Queue Backend) as the third deliverable, including: API endpoints for all seven Queues with filtering, sorting, and pagination. Phase 3 is complete when all seven Queue endpoints return valid, filtered responses.
4. WHEN Phase 3 acceptance criteria are met, THE Platform SHALL implement Phase 4 (Command Center UI) as the fourth deliverable, including: the Lead Command_Center page, Recommended_Action panel, open Tasks list, and Timeline component. Phase 4 is complete when all listed UI components are accessible and functional.
5. WHEN Phase 4 acceptance criteria are met, THE Platform SHALL implement Phase 5 (Queue UI and Row Actions) as the fifth deliverable, including: all seven Queue views with row-level action buttons, bulk selection, and optimistic UI updates. Phase 5 is complete when all seven Queue views are accessible and row actions function correctly.
6. WHEN Phase 5 acceptance criteria are met, THE Platform SHALL implement Phase 6 (Native Note/Call Logging) as the sixth deliverable, including: Log Note and Log Call forms in the Command_Center and Queue rows, call outcome Signal updates, and Timeline entries. Phase 6 is complete when notes and calls can be logged from both the Command_Center and Queue rows.
7. WHEN Phase 6 acceptance criteria are met, THE Platform SHALL implement Phase 7 (HubSpot Timeline Integration) as the seventh deliverable, including: HubSpot activity import into Timeline, `is_warm` Signal derivation, and Needs_Review_Queue triggers for new HubSpot activity. Phase 7 is complete when HubSpot activity appears in the Timeline and triggers the correct queue membership.
8. IF the acceptance criteria for Phase N are not met, THE Platform SHALL NOT begin Phase N+1 implementation.
9. WHEN a new Phase is deployed, all components delivered in prior Phases SHALL remain functional. A regression in a prior Phase component SHALL be treated as a blocking defect for the current Phase.

