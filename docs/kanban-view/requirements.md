# Feature Requirements: Kanban View with Pipeline-Based Scoring

## 1. Introduction
This document outlines the requirements for the "Kanban View with Pipeline-Based Scoring" feature within the B-B Commercial Real Estate Underwriting platform. This feature aims to provide a visual representation of deal stages using a Kanban board and integrate a scoring mechanism that leverages these stages to prioritize outreach and tasks for deal management.

## 2. User Stories

### 2.1. Kanban View
*   **As a Deal Manager,** I want to see all my deals organized by their current pipeline stage in a Kanban board, so I can quickly understand the overall status of my pipeline.
*   **As a Deal Manager,** I want to be able to drag and drop deals between stages on the Kanban board, so I can easily update their status as they progress.
*   **As a Deal Manager,** I want to see key deal information (e.g., deal name, value, assigned user) directly on each Kanban card, so I don't have to click into each deal for basic information.
*   **As a Deal Manager,** I want to be able to filter and sort the Kanban view (e.g., by assigned user, deal value, closing date), so I can focus on specific segments of my pipeline.

### 2.2. Pipeline-Based Scoring
*   **As a Deal Manager,** I want deals in later stages of the pipeline to automatically receive a higher priority score, so I can easily identify and focus on deals that are closer to closing.
*   **As a Deal Manager,** I want to see the calculated priority score clearly displayed on each deal card, so I can quickly assess its importance.
*   **As a Deal Manager,** I want the system to automatically suggest the next best action or outreach based on a deal's priority score and stage, so I can efficiently manage my workload.
*   **As an Administrator,** I want to be able to configure the scoring weight for each pipeline stage, so the scoring mechanism accurately reflects our business priorities.

## 3. Detailed Acceptance Criteria

### 3.1. Kanban View
*   **AC 3.1.1:** The Kanban board SHALL display distinct columns, each representing a defined deal pipeline stage (e.g., Lead, Qualification, Proposal, Negotiation, Closed Won, Closed Lost).
*   **AC 3.1.2:** Each deal SHALL be represented by a card within its corresponding pipeline stage column.
*   **AC 3.1.3:** Deal cards SHALL display at least the following information: Deal Name, Deal Value, Assigned User, and Priority Score.
*   **AC 3.1.4:** Users SHALL be able to drag and drop deal cards from one pipeline stage column to another.
*   **AC 3.1.5:** Upon a successful drag-and-drop, the deal's stage in the backend database SHALL be updated accordingly.
*   **AC 3.1.6:** The Kanban view SHALL support filtering by "Assigned User," "Deal Value Range," and "Expected Closing Date."
*   **AC 3.1.7:** The Kanban view SHALL support sorting by "Deal Value" (ascending/descending) and "Priority Score" (ascending/descending).
*   **AC 3.1.8:** The Kanban board SHALL visually indicate the number of deals in each stage column.

### 3.2. Pipeline-Based Scoring
*   **AC 3.2.1:** Each pipeline stage SHALL have a configurable weight assigned to it (e.g., Lead: 1, Qualification: 3, Proposal: 5, Negotiation: 8, Closed Won: 10).
*   **AC 3.2.2:** The deal's "Stage Score" SHALL be calculated based on the weight of its current pipeline stage.
*   **AC 3.2.3:** The overall "Priority Score" for a deal SHALL incorporate the "Stage Score" as a primary factor. (Further scoring criteria to be defined later, but Stage Score must be foundational).
*   **AC 3.2.4:** The "Priority Score" SHALL be dynamically updated whenever a deal's pipeline stage changes.
*   **AC 3.2.5:** The calculated "Priority Score" SHALL be prominently displayed on the deal card in the Kanban view.
*   **AC 3.2.6:** The system SHALL be able to suggest next best actions (e.g., "Follow up with client," "Prepare proposal") based on the deal's stage and Priority Score. (This could be a stretch goal for V1, but needs to be considered).
*   **AC 3.2.7:** Administrators SHALL have a dedicated interface to configure and modify the weights for each pipeline stage.

## 4. Visual Representation of Deal Stages
The Kanban view will visually represent deal stages as distinct vertical columns.
*   **Column Headers:** Each column header will clearly display the name of the pipeline stage (e.g., "New Leads," "In Qualification," "Proposal Sent").
*   **Deal Cards:** Deal cards will be contained within these columns. As deals progress, they will be moved from left to right (or in the defined order of stages).
*   **Color Coding (Optional but Recommended):** Consider using subtle color coding for deal cards or column headers to quickly indicate certain properties (e.g., deal value range, overdue tasks, high priority). This could be an enhancement for future iterations.
*   **Drag-and-Drop Feedback:** Visual feedback (e.g., highlighting target column, ghosting of the card being dragged) will be provided during drag-and-drop operations.

## 5. Scoring Mechanism and Prioritization
The scoring mechanism will directly leverage the deal's current pipeline stage to influence its priority.
*   **Stage Weighting:** Each stage will have a numerical weight. Deals in later stages will have higher weights.
*   **Priority Score Calculation:** The core "Priority Score" will be heavily influenced by this stage weight. Other factors (e.g., deal value, last activity date, close date) can be incorporated in a weighted formula to create a comprehensive score.
*   **Outreach & Task Prioritization:**
    *   **Sorting:** The Kanban view will allow sorting by Priority Score, enabling deal managers to quickly identify the most critical deals.
    *   **Filtering:** Filters can be applied to focus on high-priority deals within specific stages.
    *   **Automated Suggestions:** Based on a deal's high Priority Score and current stage, the system can recommend specific outreach actions (e.g., "Call client for follow-up on proposal" if a deal is in the "Proposal" stage with a high score).
    *   **Task List Integration:** Tasks associated with high-priority deals (influenced by their stage) should appear higher in any aggregated task lists or dashboards.

## 6. Future Considerations (Out of Scope for V1)
*   Visual indicators for overdue tasks on deal cards.
*   Customizable card display fields.
*   Integration with external CRM for automatic stage updates.
*   Advanced analytics and reporting based on pipeline velocity and scoring.
