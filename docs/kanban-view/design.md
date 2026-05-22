# Kanban View with Pipeline-Based Scoring - Technical Design Document

## 1. Introduction

This document outlines the technical design for the "Kanban View with Pipeline-Based Scoring" feature. The goal is to provide users with a visual representation of deals in a Kanban board, where each card's score is dynamically influenced by its current pipeline stage. This feature aims to enhance deal management, prioritization, and overall user experience by integrating scoring directly into the workflow.

## 2. Goals

*   **Visualize Deals:** Display deals in a Kanban board format, categorized by pipeline stages.
*   **Pipeline-Based Scoring:** Implement a scoring mechanism where the deal's score is influenced by its current pipeline stage, in addition to existing scoring factors.
*   **Real-time Updates:** Ensure that score changes and card movements are reflected in real-time.
*   **Robustness:** Design a resilient system capable of handling various data scenarios and user interactions.
*   **Simplicity:** Maintain a straightforward and easy-to-understand design for development and maintenance.
*   **Seamless Integration:** Integrate the new feature smoothly with the existing B-B-Commercial-RE-Underwriting codebase.

## 3. Data Models

### 3.1 Existing Data Models (Assumed)

*   **Deal:** Represents an underwriting deal.
    *   `id`: String (Unique identifier)
    *   `name`: String
    *   `description`: String
    *   `current_pipeline_stage_id`: String (Foreign key to PipelineStage)
    *   `score`: Integer (Current deal score, will be updated by pipeline stage)
    *   `...` (Other deal-related attributes)

*   **PipelineStage:** Represents a stage in the underwriting pipeline.
    *   `id`: String (Unique identifier)
    *   `name`: String
    *   `order`: Integer (For display order)
    *   `...` (Other stage-related attributes)

### 3.2 New/Modified Data Models

*   **PipelineStageScoring (New Field on PipelineStage Model):**
    *   `score_influence`: Integer (Represents the score boost/penalty for deals in this stage. Can be positive, negative, or zero.)

    *Rationale:* Embedding `score_influence` directly into the `PipelineStage` model simplifies data retrieval and ensures that the scoring logic is tightly coupled with the pipeline stage definition. This avoids the need for a separate junction table.

## 4. API Endpoints

### 4.1 Existing API Endpoints (Assumed)

*   `/api/deals`:
    *   `GET`: Retrieve all deals.
    *   `GET /api/deals/{id}`: Retrieve a specific deal.
    *   `PUT /api/deals/{id}`: Update a specific deal.

*   `/api/pipeline-stages`:
    *   `GET`: Retrieve all pipeline stages.

### 4.2 New/Modified API Endpoints

*   **`GET /api/kanban-deals` (New):**
    *   **Description:** Retrieves all deals, organized by pipeline stage, along with stage-specific scoring influence. This endpoint will provide all necessary data for the Kanban board in a single request.
    *   **Response Structure:**
        ```json
        [
            {
                "id": "stage1_id",
                "name": "Prospecting",
                "order": 1,
                "score_influence": 10,
                "deals": [
                    {
                        "id": "deal1_id",
                        "name": "Deal A",
                        "description": "...",
                        "current_pipeline_stage_id": "stage1_id",
                        "score": 85,
                        "...": "..."
                    },
                    {
                        "id": "deal2_id",
                        "name": "Deal B",
                        "description": "...",
                        "current_pipeline_stage_id": "stage1_id",
                        "score": 70,
                        "...": "..."
                    }
                ]
            },
            // ... other stages
        ]
        ```
    *   **Implementation Notes:**
        *   This endpoint will join `Deal` and `PipelineStage` data.
        *   The `score` for each deal returned will be its *final* score, after applying the `score_influence` from its current `PipelineStage`.

*   **`PUT /api/deals/{id}/move-stage` (Modified/New Action):**
    *   **Description:** Updates a deal's pipeline stage and recalculates its score based on the new stage's influence.
    *   **Request Body:**
        ```json
        {
            "new_pipeline_stage_id": "new_stage_id"
        }
        ```
    *   **Response:** Updated `Deal` object.
    *   **Implementation Notes:**
        *   When a deal's stage is updated, the backend will:
            1.  Retrieve the `new_pipeline_stage_id`.
            2.  Fetch the `score_influence` for the new stage.
            3.  Recalculate the deal's base score (if applicable) and then apply the `score_influence`.
            4.  Update the `deal.current_pipeline_stage_id` and `deal.score` in the database.

## 5. Frontend Components

### 5.1 Kanban Board Component

*   **Purpose:** Displays pipeline stages as columns and deals as draggable cards within those columns.
*   **Features:**
    *   **Drag-and-Drop:** Users can drag deal cards between pipeline stage columns. This action will trigger the `PUT /api/deals/{id}/move-stage` API call.
    *   **Deal Card Display:** Each card will show key deal information, including its name, a brief description, and its calculated score. The score will be prominently displayed.
    *   **Stage Columns:** Each column represents a `PipelineStage` and will display its name and potentially a count of deals within that stage.
    *   **Real-time Updates (Optional, but Recommended for Robustness):** Implement WebSockets or long-polling to reflect changes from other users or backend processes without requiring a full page refresh. This will ensure scores and card positions are always up-to-date.

### 5.2 Deal Card Component

*   **Purpose:** Displays individual deal information within a Kanban column.
*   **Features:**
    *   Deal Name
    *   Brief Description
    *   **Calculated Score:** Clearly displays the deal's score, which includes the pipeline stage's influence.
    *   (Optional) Tooltip/hover functionality to show more detailed deal information or a breakdown of the score.

## 6. Scoring Mechanism - Pipeline Influence

The scoring mechanism for a deal will be a combination of its intrinsic value (based on existing criteria) and the influence of its current pipeline stage.

### 6.1 Score Calculation Logic

`Final Deal Score = (Base Deal Score) + (PipelineStage.score_influence)`

*   **Base Deal Score:** This is the score derived from existing underwriting criteria, independent of the pipeline stage. It represents the inherent quality or potential of the deal. The details of this calculation are outside the scope of this document but are assumed to exist.
*   **PipelineStage.score_influence:** This is the integer value defined in the `PipelineStage` model.
    *   A positive `score_influence` will boost the deal's score when it is in that stage.
    *   A negative `score_influence` will penalize the deal's score.
    *   A `score_influence` of zero will have no impact.

### 6.2 Example

| Pipeline Stage | `score_influence` | Base Deal Score | Final Deal Score |
| :------------- | :---------------- | :-------------- | :--------------- |
| Prospecting    | +10               | 75              | 85               |
| Due Diligence  | +20               | 75              | 95               |
| Negotiation    | +5                | 75              | 80               |
| Closed Won     | +0                | 75              | 75               |
| Closed Lost    | -10               | 75              | 65               |

### 6.3 Implementation Details (Backend)

*   The `score_influence` will be directly managed by administrators or through configuration settings, allowing flexibility in adjusting its impact.
*   Any API endpoint that retrieves or updates a deal's score should incorporate this calculation. The `GET /api/kanban-deals` endpoint will return the final calculated score. The `PUT /api/deals/{id}/move-stage` will trigger the recalculation and update the stored `score` in the `Deal` model.

## 7. Robustness and Simplicity

### 7.1 Data Validation

*   Implement server-side validation for all API inputs (e.g., ensuring `new_pipeline_stage_id` is a valid existing stage).
*   Ensure `score_influence` is an integer.

### 7.2 Error Handling

*   Implement comprehensive error handling for API endpoints, returning meaningful error messages and appropriate HTTP status codes (e.g., 400 Bad Request, 404 Not Found, 500 Internal Server Error).
*   Frontend should gracefully handle API errors and provide user feedback.

### 7.3 Performance Considerations

*   **Database Indexing:** Ensure appropriate indexes on `Deal.current_pipeline_stage_id` and `PipelineStage.id` for efficient data retrieval in `GET /api/kanban-deals`.
*   **API Optimization:** The `GET /api/kanban-deals` endpoint should be optimized for a single, efficient database query to minimize latency.

### 7.4 Code Reusability

*   Abstract the score calculation logic into a dedicated utility function or service to be reused across different parts of the backend (e.g., when a deal is created, updated, or moved).

## 8. Integration with Existing Codebase

*   **API Layer:** Extend existing API controllers or create new ones, ensuring consistent naming conventions and authentication/authorization mechanisms.
*   **Service Layer:** Modify existing deal services or create new ones to encapsulate the business logic related to moving deals between stages and recalculating scores.
*   **Database Layer:** Update existing data access objects (DAOs) or repositories to include the `score_influence` field in `PipelineStage` and handle the score updates in `Deal`.
*   **Frontend Framework:** Utilize the existing frontend framework (e.g., React, Angular, Vue.js) components, styling, and state management solutions to ensure a cohesive user experience and development workflow.

## 9. Future Considerations

*   **Customizable Scoring Rules:** Allow users with appropriate permissions to define more complex scoring rules based on various deal attributes in addition to pipeline stage.
*   **Historical Scoring:** Track the history of a deal's score as it moves through stages and its attributes change.
*   **Analytics and Reporting:** Generate reports based on deal scores and pipeline movement to identify bottlenecks or high-performing stages.