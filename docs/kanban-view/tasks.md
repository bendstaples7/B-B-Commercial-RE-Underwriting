# Development Tasks: Kanban View with Pipeline-Based Scoring

This document outlines the granular development tasks for implementing the "Kanban View with Pipeline-Based Scoring" feature, based on the approved `requirements.md` and `design.md`.

## 1. Backend Development Tasks

### 1.1. Data Model & Migrations
- [ ] **Create `PipelineStageConfig` Model:** Implement `backend/app/models/pipeline_stage_config.py` with `stage_name`, `order`, `weight`, `created_at`, `updated_at` fields as per `design.md`.
- [ ] **Add `priority_score` to `Deal` Model:** Add `priority_score = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)` to `backend/app/models/deal.py`.
- [ ] **Generate & Apply Migrations:** Create and apply Alembic migration scripts for both `PipelineStageConfig` and the new `priority_score` field in the `Deal` model.
- [ ] **Seed Initial PipelineStageConfig Data:** Create a migration or a utility script to seed initial default pipeline stages with their names, order, and weights (e.g., Lead: 1, Qualification: 3, Proposal: 5, Negotiation: 8, Closed Won: 10, Closed Lost: 0).

### 1.2. Service Layer
- [ ] **Create `PipelineConfigService`:** Implement `backend/app/services/pipeline_config_service.py` with methods for:
    - [ ] `get_all_stages_ordered()`: Retrieves all `PipelineStageConfig` entries, ordered by `order`.
    - [ ] `get_stage_weight(stage_name)`: Returns the weight for a given stage.
    - [ ] `update_stage_weights(updates)`: Updates weights for multiple stages (admin-only).
- [ ] **Enhance `DealService` for Priority Scoring:**
    - [ ] Implement `calculate_priority_score(deal_id)` method in `backend/app/services/multifamily/deal_service.py`. This method should:
        - [ ] Fetch the deal's current `status`.
        - [ ] Retrieve the `weight` from `PipelineStageConfig` for that status.
        - [ ] Calculate the overall `priority_score` using the `Stage Score` as a primary factor, potentially incorporating other attributes like `deal_value`. (Final formula to be determined/refined).
        - [ ] Update the `deal.priority_score` field.
    - [ ] Integrate `calculate_priority_score` call into `DealService.update_deal` so score is recalculated when `status` changes.
    - [ ] Implement a trigger or scheduled task to recalculate `priority_score` for all relevant deals (e.g., a background job).

### 1.3. API Endpoints
- [ ] **Create `pipeline_config_controller.py`:** Implement a new Flask Blueprint for pipeline configuration.
    - [ ] Define `GET /pipeline-stages` endpoint: Returns an ordered list of pipeline stages with `stage_name`, `order`, `weight`.
    - [ ] Define `PUT /pipeline-stages/weights` endpoint: Accepts a list of `{stage_name: weight}` pairs to update stage weights (admin-only, requires authentication/authorization).
- [ ] **Update `multifamily_deal_controller.py`:** Ensure existing `GET /deals` and `PATCH /deals/<int:deal_id>` endpoints function correctly with the `Deal.status` and new `priority_score` fields.
    - [ ] Ensure `GET /deals` can return `priority_score` in its response schema.
    - [ ] Ensure `PATCH /deals/<int:deal_id>` can trigger `priority_score` recalculation when `status` is updated.

### 1.4. Backend Schemas
- [ ] **Create `PipelineStageConfigSchema`:** Define Pydantic schema for `PipelineStageConfig` model.
- [ ] **Update `DealSchema`:** Include the new `priority_score` field in the response schema for `GET /deals`.
- [ ] **Update `DealUpdateSchema`:** Ensure `status` field is correctly handled, and optionally include `priority_score` if frontend can override (though design assumes backend calculation).

## 2. Frontend Development Tasks

### 2.1. Core Kanban UI Components
- [ ] **Create `DealKanbanPage.tsx`:**
    - [ ] Main page component for the Kanban view.
    - [ ] Fetches `PipelineStageConfig` and initial deal data for all stages.
    - [ ] Manages overall Kanban board state (stages, deals per stage, filters, sorting).
    - [ ] Orchestrates `KanbanColumn` rendering.
- [ ] **Create `KanbanColumn.tsx`:**
    - [ ] Renders a single pipeline stage column.
    - [ ] Displays the stage name as header.
    - [ ] Displays deal count for the stage (AC 3.1.8).
    - [ ] Renders `DealCard` components for deals in its stage.
    - [ ] Implements drop target functionality for drag-and-drop.
- [ ] **Create `DealCard.tsx`:**
    - [ ] Displays key deal information: Deal Name, Deal Value, Assigned User, Priority Score (AC 3.1.3).
    - [ ] Implements draggable functionality.
    - [ ] Integrates `LeadScoreBadge.tsx` for `priority_score` display.

### 2.2. State Management
- [ ] **Create `DealKanbanContext.tsx`:**
    - [ ] Implement React Context for managing Kanban board state.
    - [ ] Provides pipeline stage configuration, deals organized by stage, active filters, and sorting state.
    - [ ] Includes functions to update deal stages (calling backend API).

### 2.3. Data Flow & Interaction
- [ ] **Data Fetching:** Implement logic in `DealKanbanPage` or `DealKanbanContext` to fetch:
    - [ ] Pipeline stage configuration from `GET /pipeline-stages`.
    - [ ] Deals for each stage from `GET /deals?status=<stage_name>`.
- [ ] **Drag-and-Drop Functionality:**
    - [ ] Integrate a React drag-and-drop library (e.g., `dnd-kit`).
    - [ ] Implement drag logic for `DealCard.tsx`.
    - [ ] Implement drop logic for `KanbanColumn.tsx`.
    - [ ] On drop, update the deal's stage in the frontend state and send a `PATCH /deals/<int:deal_id>` request to the backend.
- [ ] **Filtering and Sorting Controls:** Adapt filtering and sorting UI from `PropertyListPage.tsx` and integrate into `DealKanbanPage.tsx` (AC 3.1.6, 3.1.7).

### 2.4. Admin Interface for Stage Weights
- [ ] **Create `PipelineConfigAdminPage.tsx` (or similar):**
    - [ ] Admin-only interface to display and edit `PipelineStageConfig` (stage names, order, weights).
    - [ ] Fetches current configuration from `GET /pipeline-stages`.
    - [ ] Allows editing of weights.
    - [ ] Sends updates via `PUT /pipeline-stages/weights`.

## 3. Testing Tasks

### 3.1. Backend Testing
- [ ] **Unit Tests for `PipelineStageConfig` Model:**
    - [ ] Test creation, retrieval, update, deletion of stage configurations.
    - [ ] Test uniqueness constraints for `stage_name` and `order`.
- [ ] **Unit Tests for `DealService.calculate_priority_score`:**
    - [ ] Test score calculation based on various stage weights.
    - [ ] Test score recalculation upon `Deal.status` change.
- [ ] **API Integration Tests for `/pipeline-stages`:**
    - [ ] Test `GET /pipeline-stages` endpoint for correct data retrieval and ordering.
    - [ ] Test `PUT /pipeline-stages/weights` endpoint (admin-only, authorization checks).
- [ ] **API Integration Tests for `/deals` (Kanban context):**
    - [ ] Test `GET /deals?status=<stage_name>` for accurate filtering.
    - [ ] Test `PATCH /deals/<int:deal_id>` to ensure `status` updates and `priority_score` recalculations are correct.

### 3.2. Frontend Testing
- [ ] **Component Tests for `DealCard.tsx`:**
    - [ ] Test rendering of deal information and `priority_score`.
    - [ ] Test draggable behavior.
- [ ] **Component Tests for `KanbanColumn.tsx`:**
    - [ ] Test rendering of column header and deal count.
    - [ ] Test rendering of `DealCard` components.
    - [ ] Test drop target behavior.
- [ ] **Page/Integration Tests for `DealKanbanPage.tsx`:**
    - [ ] Test full Kanban board rendering with data from backend.
    - [ ] Test drag-and-drop functionality end-to-end (UI to API).
    - [ ] Test filtering and sorting interactions.
- [ ] **Admin UI Tests for `PipelineConfigAdminPage.tsx`:**
    - [ ] Test display and editing of pipeline stage weights.
    - [ ] Test sending updates to backend.

## 4. Documentation Updates
- [ ] **Update API Documentation:** Add new API endpoints and schemas to `backend/API_DOCUMENTATION.md` or similar.
- [ ] **Update Frontend README/Docs:** Add notes on new Kanban components and their usage.

---