"""OpenAPI spec generation for the Real Estate Analysis Platform.

Exposes a minimal OpenAPI 3.0 spec at GET /api/openapi.json that documents
the most critical endpoints: HubSpot, leads, organizations, interactions,
and tasks.

Usage
-----
The spec is generated at runtime from the route registry and the Pydantic
models defined here.  It is intentionally kept separate from the main app
factory so it can be imported without side-effects.

To regenerate TypeScript types from the spec::

    npm run generate-types   # in frontend/

This requires the backend to be running on port 5000.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify

openapi_bp = Blueprint("openapi", __name__)


# ---------------------------------------------------------------------------
# Inline OpenAPI 3.0 spec
# ---------------------------------------------------------------------------
# We build the spec as a plain Python dict rather than using flask-openapi3's
# decorator-heavy approach so we don't have to rewrite every existing route.
# The spec documents the *shapes* that the controllers actually return, which
# is the source of truth for the TypeScript type generator.

_SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "Real Estate Analysis Platform API",
        "version": "1.0.0",
        "description": (
            "API for the B and B Real Estate Analyzer — property analysis, "
            "lead management, HubSpot CRM migration, and multifamily underwriting."
        ),
    },
    "servers": [{"url": "/api", "description": "Local development server"}],
    "paths": {
        # ------------------------------------------------------------------
        # HubSpot — config
        # ------------------------------------------------------------------
        "/hubspot/config": {
            "get": {
                "tags": ["HubSpot"],
                "summary": "Get HubSpot configuration",
                "operationId": "getHubSpotConfig",
                "responses": {
                    "200": {
                        "description": "Current HubSpot config (token masked) or unconfigured state",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotConfig"}
                            }
                        },
                    }
                },
            },
            "post": {
                "tags": ["HubSpot"],
                "summary": "Save HubSpot API token",
                "operationId": "saveHubSpotConfig",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["token"],
                                "properties": {
                                    "token": {"type": "string"},
                                    "portal_id": {"type": "string", "nullable": True},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Saved config",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotConfig"}
                            }
                        },
                    }
                },
            },
        },
        "/hubspot/config/test": {
            "post": {
                "tags": ["HubSpot"],
                "summary": "Test HubSpot connection",
                "operationId": "testHubSpotConnection",
                "responses": {
                    "200": {
                        "description": "Connection test result",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotConnectionTest"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # HubSpot — import runs
        # ------------------------------------------------------------------
        "/hubspot/import/trigger": {
            "post": {
                "tags": ["HubSpot"],
                "summary": "Trigger a HubSpot import",
                "operationId": "triggerHubSpotImport",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "object_types": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "nullable": True,
                                    }
                                },
                            }
                        }
                    }
                },
                "responses": {
                    "202": {
                        "description": "Import started",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "run_ids": {
                                            "type": "array",
                                            "items": {"type": "integer"},
                                        },
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/hubspot/import/runs": {
            "get": {
                "tags": ["HubSpot"],
                "summary": "List import runs",
                "operationId": "listImportRuns",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of import runs",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotImportRunList"}
                            }
                        },
                    }
                },
            }
        },
        "/hubspot/import/runs/{run_id}": {
            "get": {
                "tags": ["HubSpot"],
                "summary": "Get a single import run",
                "operationId": "getImportRun",
                "parameters": [
                    {"name": "run_id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {
                        "description": "Import run detail",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotImportRun"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # HubSpot — review queue
        # ------------------------------------------------------------------
        "/hubspot/review-queue": {
            "get": {
                "tags": ["HubSpot"],
                "summary": "List review queue items",
                "operationId": "listReviewQueue",
                "parameters": [
                    {"name": "type", "in": "query", "schema": {"type": "string"}},
                    {"name": "confidence", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of HubSpot match records",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HubSpotMatchList"}
                            }
                        },
                    }
                },
            }
        },
        "/hubspot/pipeline/status": {
            "get": {
                "tags": ["HubSpot"],
                "summary": "Get pipeline status",
                "operationId": "getPipelineStatus",
                "responses": {
                    "200": {
                        "description": "Pipeline running state and record counts",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PipelineStatus"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Leads
        # ------------------------------------------------------------------
        "/leads/": {
            "get": {
                "tags": ["Leads"],
                "summary": "List leads",
                "operationId": "listLeads",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                    {"name": "property_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "lead_category", "in": "query", "schema": {"type": "string"}},
                    {"name": "score_min", "in": "query", "schema": {"type": "number"}},
                    {"name": "score_max", "in": "query", "schema": {"type": "number"}},
                    {"name": "sort_by", "in": "query", "schema": {"type": "string"}},
                    {"name": "sort_order", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of leads",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LeadList"}
                            }
                        },
                    }
                },
            }
        },
        "/leads/{lead_id}": {
            "get": {
                "tags": ["Leads"],
                "summary": "Get lead detail",
                "operationId": "getLead",
                "parameters": [
                    {"name": "lead_id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {
                        "description": "Full lead detail",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LeadDetail"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Lead views
        # ------------------------------------------------------------------
        "/leads/views/previously-warm": {
            "get": {
                "tags": ["Leads", "Views"],
                "summary": "Leads with warm conversation signals",
                "operationId": "viewPreviouslyWarm",
                "responses": {
                    "200": {
                        "description": "Paginated lead list",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LeadList"}
                            }
                        },
                    }
                },
            }
        },
        "/leads/views/needs-review": {
            "get": {
                "tags": ["Leads", "Views"],
                "summary": "HubSpot-imported leads needing review",
                "operationId": "viewNeedsReview",
                "responses": {
                    "200": {
                        "description": "Paginated lead list",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LeadList"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Organizations
        # ------------------------------------------------------------------
        "/organizations/": {
            "get": {
                "tags": ["Organizations"],
                "summary": "List organizations",
                "operationId": "listOrganizations",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                    {"name": "name", "in": "query", "schema": {"type": "string"}},
                    {"name": "org_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of organizations",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/OrganizationList"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Interactions
        # ------------------------------------------------------------------
        "/interactions/": {
            "get": {
                "tags": ["Interactions"],
                "summary": "List interactions",
                "operationId": "listInteractions",
                "parameters": [
                    {"name": "target_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "target_id", "in": "query", "schema": {"type": "integer"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of interactions",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/InteractionList"}
                            }
                        },
                    }
                },
            }
        },
        # ------------------------------------------------------------------
        # Tasks
        # ------------------------------------------------------------------
        "/tasks/": {
            "get": {
                "tags": ["Tasks"],
                "summary": "List tasks",
                "operationId": "listTasks",
                "parameters": [
                    {"name": "status", "in": "query", "schema": {"type": "string"}},
                    {"name": "priority", "in": "query", "schema": {"type": "string"}},
                    {"name": "target_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "target_id", "in": "query", "schema": {"type": "integer"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {
                    "200": {
                        "description": "Paginated list of tasks",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TaskList"}
                            }
                        },
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            # ------------------------------------------------------------------
            # HubSpot schemas
            # ------------------------------------------------------------------
            "HubSpotConfig": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "portal_id": {"type": "string", "nullable": True},
                    "account_name": {"type": "string", "nullable": True},
                    "configured_at": {"type": "string", "format": "date-time", "nullable": True},
                    "configured": {"type": "boolean"},
                },
            },
            "HubSpotConnectionTest": {
                "type": "object",
                "required": ["success"],
                "properties": {
                    "success": {"type": "boolean"},
                    "account_name": {"type": "string"},
                    "portal_id": {"type": "string"},
                    "error": {"type": "string"},
                },
            },
            "HubSpotImportRun": {
                "type": "object",
                "required": ["id", "object_type", "status"],
                "properties": {
                    "id": {"type": "integer"},
                    "object_type": {"type": "string"},
                    "status": {"type": "string"},
                    "start_time": {"type": "string", "format": "date-time", "nullable": True},
                    "end_time": {"type": "string", "format": "date-time", "nullable": True},
                    "total_fetched": {"type": "integer"},
                    "created_count": {"type": "integer"},
                    "updated_count": {"type": "integer"},
                    "skipped_count": {"type": "integer"},
                    "error_count": {"type": "integer"},
                    "error_message": {"type": "string", "nullable": True},
                },
            },
            "HubSpotImportRunList": {
                "type": "object",
                "required": ["runs", "total", "page", "per_page", "pages"],
                "properties": {
                    "runs": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/HubSpotImportRun"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                    "pages": {"type": "integer"},
                },
            },
            "HubSpotMatch": {
                "type": "object",
                "required": ["id", "hubspot_record_type", "hubspot_id", "confidence", "status"],
                "properties": {
                    "id": {"type": "integer"},
                    "hubspot_record_type": {"type": "string"},
                    "hubspot_id": {"type": "string"},
                    "internal_record_type": {"type": "string", "nullable": True},
                    "internal_record_id": {"type": "integer", "nullable": True},
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW", "UNMATCHED"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "confirmed", "rejected"],
                    },
                    "matching_criteria": {"type": "string", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "HubSpotMatchList": {
                "type": "object",
                "required": ["matches", "total", "page", "per_page", "pages", "pending_count"],
                "properties": {
                    "matches": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/HubSpotMatch"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                    "pages": {"type": "integer"},
                    "pending_count": {"type": "integer"},
                },
            },
            "PipelineStatus": {
                "type": "object",
                "required": ["pipeline_running", "matches", "interactions", "tasks", "signals"],
                "properties": {
                    "pipeline_running": {"type": "boolean"},
                    "matches": {
                        "type": "object",
                        "properties": {
                            "total": {"type": "integer"},
                            "high": {"type": "integer"},
                            "medium": {"type": "integer"},
                            "unmatched": {"type": "integer"},
                        },
                    },
                    "interactions": {"type": "integer"},
                    "tasks": {"type": "integer"},
                    "signals": {"type": "integer"},
                },
            },
            # ------------------------------------------------------------------
            # Lead schemas
            # ------------------------------------------------------------------
            "LeadSummary": {
                "type": "object",
                "required": ["id", "property_street", "lead_score", "lead_category"],
                "properties": {
                    "id": {"type": "integer"},
                    "property_street": {"type": "string"},
                    "property_city": {"type": "string", "nullable": True},
                    "property_state": {"type": "string", "nullable": True},
                    "property_zip": {"type": "string", "nullable": True},
                    "property_type": {"type": "string", "nullable": True},
                    "owner_first_name": {"type": "string"},
                    "owner_last_name": {"type": "string"},
                    "lead_score": {"type": "number"},
                    "lead_category": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time", "nullable": True},
                    "updated_at": {"type": "string", "format": "date-time", "nullable": True},
                },
            },
            "LeadList": {
                "type": "object",
                "required": ["leads", "total", "page", "per_page", "pages"],
                "properties": {
                    "leads": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/LeadSummary"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                    "pages": {"type": "integer"},
                },
            },
            "LeadDetail": {
                "allOf": [
                    {"$ref": "#/components/schemas/LeadSummary"},
                    {
                        "type": "object",
                        "properties": {
                            "enrichment_records": {"type": "array", "items": {"type": "object"}},
                            "marketing_lists": {"type": "array", "items": {"type": "object"}},
                            "analysis_session": {"type": "object", "nullable": True},
                        },
                    },
                ]
            },
            # ------------------------------------------------------------------
            # Organization schemas
            # ------------------------------------------------------------------
            "Organization": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "org_type": {"type": "string"},
                    "status": {"type": "string"},
                    "notes": {"type": "string", "nullable": True},
                    "source": {"type": "string", "nullable": True},
                    "hubspot_company_id": {"type": "string", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "OrganizationList": {
                "type": "object",
                "required": ["organizations", "total", "page", "per_page", "pages"],
                "properties": {
                    "organizations": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Organization"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                    "pages": {"type": "integer"},
                },
            },
            # ------------------------------------------------------------------
            # Interaction schemas
            # ------------------------------------------------------------------
            "Interaction": {
                "type": "object",
                "required": ["id", "interaction_type", "body", "occurred_at"],
                "properties": {
                    "id": {"type": "integer"},
                    "interaction_type": {"type": "string"},
                    "body": {"type": "string"},
                    "occurred_at": {"type": "string", "format": "date-time"},
                    "source": {"type": "string"},
                    "hubspot_engagement_id": {"type": "string", "nullable": True},
                    "is_orphaned": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time", "nullable": True},
                    "updated_at": {"type": "string", "format": "date-time", "nullable": True},
                    "associations": {"type": "array", "items": {"type": "object"}},
                },
            },
            "InteractionList": {
                "type": "object",
                "required": ["interactions", "total", "page", "per_page"],
                "properties": {
                    "interactions": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Interaction"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                },
            },
            # ------------------------------------------------------------------
            # Task schemas
            # ------------------------------------------------------------------
            "CRMTask": {
                "type": "object",
                "required": ["id", "title", "status", "priority"],
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "body": {"type": "string", "nullable": True},
                    "due_date": {"type": "string", "format": "date-time", "nullable": True},
                    "status": {"type": "string"},
                    "priority": {"type": "string"},
                    "source": {"type": "string"},
                    "hubspot_task_id": {"type": "string", "nullable": True},
                    "completion_timestamp": {"type": "string", "format": "date-time", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time", "nullable": True},
                    "updated_at": {"type": "string", "format": "date-time", "nullable": True},
                    "associations": {"type": "array", "items": {"type": "object"}},
                },
            },
            "TaskList": {
                "type": "object",
                "required": ["tasks", "total", "page", "per_page"],
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/CRMTask"},
                    },
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "per_page": {"type": "integer"},
                },
            },
        }
    },
}


@openapi_bp.route("/openapi.json", methods=["GET"])
def get_openapi_spec():
    """Return the OpenAPI 3.0 spec as JSON.

    This endpoint is intentionally unauthenticated so that ``openapi-typescript``
    can fetch it without credentials during local development.
    """
    return jsonify(_SPEC), 200
