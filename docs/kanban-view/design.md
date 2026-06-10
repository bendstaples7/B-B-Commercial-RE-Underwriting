# Revised Design: Kanban View with Pipeline-Based Scoring

## 1. Introduction & Goals

This document outlines the revised design for the 'Kanban View with Pipeline-Based Scoring' feature, incorporating detailed analysis of the existing `B-B-Commercial-RE-Underwriting` codebase and aligning with the approved requirements. The primary goals are to provide a visual, interactive Kanban board for deal management and to integrate a robust, configurable pipeline-based scoring mechanism to prioritize deals. This design emphasizes seamless integration with existing data models and API endpoints, while proposing new frontend components and state management for the Kanban interface.

## 2. Revised Data Model

**Confirmed Assumption:** The existing `Deal` model's `status` field (`backend/app/models/deal.py`, line 45: `status = db.Column(db.String(50), nullable=False, default='draft')`) will be leveraged to represent the pipeline stage of a deal. This avoids modifying the core `Deal` table structure.

**Proposed Integration Point:**
*   **Pipeline Stage Definitions & Weights:**
    *   **Assumption:** Pipeline stages (e.g., 'Lead', 'Qualification', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost') will be managed as a predefined, ordered list on the frontend initially.
    *   **Integration:** For administrator-configurable scoring weights per stage (AC 3.2.7), a new database table, e.g., `PipelineStageConfig`, is proposed. This table would store `stage_name` (string, unique), `order` (integer), and `weight` (float/decimal). This allows the backend to serve the configurable weights and stage order to the frontend, and to use these weights in scoring calculations.

**Data Model Changes (Proposed):**
*   **`PipelineStageConfig` (New Model):**
    ```python
    # backend/app/models/pipeline_stage_config.py (New File)
    from app import db
    from datetime import datetime

    class PipelineStageConfig(db.Model):
        __tablename__ = 'pipeline_stage_config'

        id = db.Column(db.Integer, primary_key=True)
        stage_name = db.Column(db.String(50), unique=True, nullable=False, index=True)
        order = db.Column(db.Integer, nullable=False, unique=True)
        weight = db.Column(db.Numeric(8, 6), nullable=False, default=1.0) # For scoring
        created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        def __repr__(self):
            return f'<PipelineStageConfig {self.stage_name} (Order: {self.order}, Weight: {self.weight})>'
    ```
*   **`Deal` Model Enhancement (Implicit):** The `Deal.status` field will now store one of the `stage_name` values defined in `PipelineStageConfig`.

## 3. API Endpoints & Integration

**Confirmed Integration Points:**
*   **Fetching Deals for Kanban Columns:**
    *   **Endpoint:** `GET /deals` (`backend/app/controllers/multifamily_deal_controller.py`, `list_deals`)
    *   **Assumption Confirmed:** This endpoint already supports filtering by `status` (line 123-124), allowing the frontend to fetch deals for specific pipeline stages by providing `?status=<stage_name>`.
    *   **Integration:** The frontend will make multiple `GET /deals` requests, one for each pipeline stage, to populate the respective Kanban columns.
*   **Updating Deal Stage (Drag-and-Drop):**
    *   **Endpoint:** `PATCH /deals/<int:deal_id>` (`backend/app/controllers/multifamily_deal_controller.py`, `update_deal`)
    *   **Assumption Confirmed:** The `DealUpdateSchema` (`backend/app/schemas.py`, line 613) includes the `status` field, and `DealService.update_deal` (`backend/app/services/multifamily/deal_service.py`, line 190) allows its modification.
    *   **Integration:** When a user drags and drops a deal card, the frontend will send a `PATCH` request to this endpoint with the `deal_id` and the new `status` (stage name).

**Proposed New API Endpoints:**
*   **Get Pipeline Stage Configuration:**
    *   **Endpoint:** `GET /pipeline-stages`
    *   **Purpose:** To retrieve the ordered list of pipeline stage names and their associated weights, as defined in `PipelineStageConfig`. This will be used by the frontend to render the Kanban columns and calculate scores.
    *   **Controller:** A new controller (e.g., `pipeline_config_controller.py`) and service (e.g., `PipelineConfigService.py`) would be created.
*   **Update Pipeline Stage Weights (Admin):**
    *   **Endpoint:** `PUT /pipeline-stages/weights`
    *   **Purpose:** To allow administrators to configure the scoring weights for each pipeline stage (AC 3.2.7).
    *   **Controller:** Part of the new `pipeline_config_controller.py`.

## 4. Frontend Architecture

The Kanban view will be a new top-level page/component, likely `DealKanbanPage.tsx`, within `frontend/src/pages/` or `frontend/src/components/`.

**New Components:**
*   **`DealKanbanPage.tsx`:** The main container for the Kanban board, responsible for orchestrating data fetching, state management, and rendering `KanbanColumn` components.
*   **`KanbanColumn.tsx`:** Represents a single pipeline stage. It will receive a list of deals for its stage and render `DealCard` components. It will also handle drop events for deals being moved into its column.
*   **`DealCard.tsx`:** Represents an individual deal on the Kanban board. It will display key deal information (Deal Name, Deal Value, Assigned User, Priority Score - AC 3.1.3). It will be draggable.

**Reused Elements:**
*   **Data Fetching Logic:** The patterns used in `PropertyListPage.tsx` for fetching data (using `useQueries` or similar hooks with `dealService.listDeals`) can be adapted.
*   **`LeadScoreBadge.tsx`:** Can be directly reused or adapted to display the `Priority Score` on `DealCard` components.
*   **Filtering and Sorting Controls:** The filtering and sorting mechanisms from `PropertyListPage.tsx` can be adapted and integrated into `DealKanbanPage.tsx` to meet AC 3.1.6 and 3.1.7.

**Data Flow (Frontend):**
1.  `DealKanbanPage` fetches the `PipelineStageConfig` (ordered stages and weights) from the new `GET /pipeline-stages` endpoint.
2.  For each stage, `DealKanbanPage` or a child component makes a `GET /deals?status=<stage_name>` request to retrieve deals for that column.
3.  Deals are then passed down to `KanbanColumn` components, which in turn render `DealCard` components.
4.  Drag-and-drop actions on `DealCard`s trigger an update:
    *   The new `status` (stage name) is extracted.
    *   A `PATCH /deals/<int:deal_id>` request is sent to the backend with the updated status.
    *   On successful update, the frontend state is updated to reflect the deal's new position, potentially refetching deals for the affected columns or optimistically updating the UI.

## 5. State Management

**Proposed New State Management:**
Given that the existing `PipelineStatusContext` is for HubSpot, a new, dedicated state management solution will be implemented for the Kanban board.

*   **Option 1 (React Context API):** A new `DealKanbanContext.tsx` can be created to manage the overall state of the Kanban board, including:
    *   The list of pipeline stages (from `PipelineStageConfig`).
    *   A dictionary or map of deals, organized by their current stage.
    *   State for active filters and sort order.
    *   Functions for updating deal status (which will call the backend API) and managing UI re-renders.
*   **Option 2 (Redux Toolkit / Zustand):** For more complex state management, especially if the Kanban board becomes highly interactive with many concurrent updates or complex business logic on the frontend, a state management library like Redux Toolkit or Zustand could be considered. However, for initial V1, React Context with `useReducer` or `useState` might suffice for simplicity.

**Decision for V1:** Start with a dedicated React Context (`DealKanbanContext`) for simplicity and evaluate the need for a more robust library if complexity increases.

## 6. Scoring Integration

**Confirmed Assumption:** The `Deal` model already includes fields like `purchase_price` and `unit_count` that can contribute to a comprehensive `Priority Score`.

**Proposed Integration Points:**
*   **Stage Score Calculation:** The `Stage Score` (AC 3.2.2) will be derived directly from the `weight` associated with the deal's `status` (pipeline stage), as retrieved from the `PipelineStageConfig` via the `GET /pipeline-stages` endpoint.
*   **Overall Priority Score (Backend):**
    *   **Assumption:** The overall `Priority Score` will be calculated on the backend.
    *   **Integration:** A new field, e.g., `priority_score` (numeric), will be added to the `Deal` model. A new service method (e.g., `DealService.calculate_priority_score`) will be responsible for calculating this score based on the `Deal.status` (using `PipelineStageConfig.weight`) and other deal attributes (e.g., deal value, time in stage, etc., as per AC 3.2.3).
    *   This score will be recalculated whenever the `Deal.status` is updated or other relevant deal fields change.
    *   **`Deal` Model Enhancement (Proposed):**
        ```python
        # In backend/app/models/deal.py
        class Deal(db.Model):
            # ... existing fields ...
            priority_score = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
            # ... existing fields ...
        ```
*   **Admin Interface for Weights:**
    *   **Frontend:** A new admin-only page/component will be created to list and update the `PipelineStageConfig` (stage names, order, weights). This will use the new `GET /pipeline-stages` and `PUT /pipeline-stages/weights` API endpoints.
    *   **Backend:** `PipelineConfigService` will handle the business logic for managing `PipelineStageConfig`.
*   **Displaying Priority Score:** The `DealCard.tsx` component will display the `priority_score` using a `LeadScoreBadge` or a similar visual indicator (AC 3.2.5).

## 7. Assumptions & Confirmations

**Confirmed Assumptions/Integration Points:**
*   **Deal Status as Pipeline Stage:** The `Deal.status` field is confirmed as the mechanism for tracking pipeline stages.
*   **Existing API for Status Update:** The `PATCH /deals/<int:deal_id>` endpoint is confirmed for updating deal status.
*   **Existing API for Filtering by Status:** The `GET /deals` endpoint supports filtering by `status` for populating Kanban columns.
*   **Reusable Frontend Data Logic:** Data fetching and basic filtering patterns from `PropertyListPage.tsx` can be adapted.
*   **Reusable Frontend Scoring Component:** `LeadScoreBadge.tsx` can be reused for displaying scores.

**Proposed Integration Points/Assumptions Requiring New Development:**
*   **New `PipelineStageConfig` Model and CRUD API:** For configurable stage names, order, and weights.
*   **Backend `priority_score` field in `Deal` model:** To store the calculated priority score.
*   **Backend `DealService` method for `priority_score` calculation:** To update the score based on stage weights and other factors.
*   **New Frontend Kanban Components:** `DealKanbanPage.tsx`, `KanbanColumn.tsx`, `DealCard.tsx`.
*   **New Frontend State Management:** A dedicated `DealKanbanContext` for the Kanban board.
*   **New Frontend Admin Interface:** For configuring pipeline stage weights.
*   **Drag-and-Drop Library:** A suitable frontend library (e.g., `react-beautiful-dnd` or `dnd-kit`) will be needed to implement the drag-and-drop functionality for `DealCard`s between `KanbanColumn`s.

## 8. Next Steps

1.  Implement the `PipelineStageConfig` model and associated backend service and API endpoints.
2.  Add `priority_score` field to the `Deal` model and implement the calculation logic in `DealService`.
3.  Develop the frontend `DealKanbanPage`, `KanbanColumn`, and `DealCard` components.
4.  Integrate drag-and-drop functionality for updating deal statuses.
5.  Implement the admin interface for configuring pipeline stage weights.
6.  Thorough testing of both backend and frontend components, especially for data consistency and real-time updates.
