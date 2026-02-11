# Real Estate Analysis Platform - API Documentation

## Base URL
```
http://localhost:5000/api
```

## Rate Limits
- Default: 200 requests per day, 50 requests per hour
- Start Analysis: 10 requests per minute
- Get Session State: 30 requests per minute
- Advance/Update/Back: 20 requests per minute
- Generate Report: 10 requests per minute
- Export: 5 requests per minute

## Authentication
Currently, authentication is handled via `user_id` in requests. Future versions will implement OAuth2.

## Endpoints

### Health Check
Check API health status.

**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy"
}
```

---

### Start Analysis
Start a new analysis session with a property address.

**Endpoint:** `POST /analysis/start`

**Request Body:**
```json
{
  "address": "123 Main St, Chicago, IL 60601",
  "user_id": "user123"
}
```

**Response:** `201 Created`
```json
{
  "session_id": "uuid-string",
  "user_id": "user123",
  "current_step": "PROPERTY_FACTS",
  "created_at": "2024-01-01T00:00:00",
  "status": "initialized"
}
```

**Errors:**
- `400 Bad Request`: Invalid or missing fields

---

### Get Session State
Retrieve the current state of an analysis session.

**Endpoint:** `GET /analysis/{session_id}`

**Response:** `200 OK`
```json
{
  "session_id": "uuid-string",
  "user_id": "user123",
  "current_step": "PROPERTY_FACTS",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00",
  "subject_property": { ... },
  "comparables": [ ... ],
  "comparable_count": 10,
  "ranked_comparables": [ ... ],
  "valuation_result": { ... },
  "scenarios": [ ... ]
}
```

**Errors:**
- `400 Bad Request`: Session not found

---

### Advance to Step
Advance the workflow to the next step.

**Endpoint:** `POST /analysis/{session_id}/step/{step_number}`

**Step Numbers:**
1. Property Facts
2. Comparable Search
3. Comparable Review
4. Weighted Scoring
5. Valuation Models
6. Report Generation

**Request Body:**
```json
{
  "approval_data": { ... }  // Optional
}
```

**Response:** `200 OK`
```json
{
  "session_id": "uuid-string",
  "current_step": "COMPARABLE_SEARCH",
  "previous_step": "PROPERTY_FACTS",
  "result": { ... },
  "updated_at": "2024-01-01T00:00:00"
}
```

**Errors:**
- `400 Bad Request`: Invalid step number, session not found, or step not complete

---

### Update Step Data
Update data for a specific workflow step.

**Endpoint:** `PUT /analysis/{session_id}/step/{step_number}`

**Request Body (Step 1 - Property Facts):**
```json
{
  "address": "456 Oak Ave, Chicago, IL 60601",
  "property_type": "MULTI_FAMILY",
  "units": 4,
  "bedrooms": 8,
  "bathrooms": 4.0,
  "square_footage": 3200,
  "lot_size": 5000,
  "year_built": 1920,
  "construction_type": "BRICK",
  "basement": true,
  "parking_spaces": 2,
  "assessed_value": 250000.0,
  "annual_taxes": 5000.0,
  "zoning": "R-4",
  "interior_condition": "AVERAGE"
}
```

**Request Body (Step 3 - Comparable Review):**
```json
{
  "action": "remove",
  "comparable_id": 123
}
```
or
```json
{
  "action": "add",
  "address": "789 Elm St",
  "sale_date": "2024-01-01",
  "sale_price": 300000.0,
  "property_type": "MULTI_FAMILY",
  "units": 4,
  "bedrooms": 8,
  "bathrooms": 4.0,
  "square_footage": 3200,
  "lot_size": 5000,
  "year_built": 1920,
  "construction_type": "BRICK",
  "interior_condition": "AVERAGE",
  "distance_miles": 0.5
}
```

**Response:** `200 OK`
```json
{
  "session_id": "uuid-string",
  "step": "PROPERTY_FACTS",
  "updated_data": { ... },
  "recalculations": [ ... ],
  "updated_at": "2024-01-01T00:00:00"
}
```

**Errors:**
- `400 Bad Request`: Invalid data or validation errors

---

### Go Back to Step
Navigate backward to a previous workflow step.

**Endpoint:** `POST /analysis/{session_id}/back/{step_number}`

**Response:** `200 OK`
```json
{
  "session_id": "uuid-string",
  "user_id": "user123",
  "current_step": "PROPERTY_FACTS",
  "previous_step": "COMPARABLE_SEARCH",
  "navigation": "backward",
  ...
}
```

**Errors:**
- `400 Bad Request`: Invalid step number or cannot go forward

---

### Generate Report
Generate a comprehensive analysis report.

**Endpoint:** `GET /analysis/{session_id}/report`

**Response:** `200 OK`
```json
{
  "report": {
    "section_a": { ... },
    "section_b": { ... },
    "section_c": { ... },
    "section_d": { ... },
    "section_e": { ... },
    "section_f": { ... }
  }
}
```

**Errors:**
- `404 Not Found`: Session not found

---

### Export to Excel
Export the analysis report to Excel format.

**Endpoint:** `GET /analysis/{session_id}/export/excel`

**Response:** `200 OK`
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Binary Excel file download

**Errors:**
- `404 Not Found`: Session not found

---

### Export to Google Sheets
Export the analysis report to Google Sheets.

**Endpoint:** `POST /analysis/{session_id}/export/sheets`

**Request Body:**
```json
{
  "credentials": {
    // Google OAuth credentials
  }
}
```

**Response:** `200 OK`
```json
{
  "url": "https://docs.google.com/spreadsheets/d/...",
  "message": "Report exported successfully to Google Sheets"
}
```

**Errors:**
- `400 Bad Request`: Missing credentials
- `404 Not Found`: Session not found

---

## Error Response Format

All error responses follow this format:

```json
{
  "error": "Error type",
  "message": "Detailed error message",
  "details": { ... }  // Optional, for validation errors
}
```

### Common Error Codes
- `400 Bad Request`: Invalid input or validation error
- `404 Not Found`: Resource not found
- `415 Unsupported Media Type`: Missing or incorrect Content-Type header
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Unexpected server error

---

## Enumerations

### Property Type
- `SINGLE_FAMILY`
- `MULTI_FAMILY`
- `COMMERCIAL`

### Construction Type
- `FRAME`
- `BRICK`
- `MASONRY`
- `CONCRETE`
- `STEEL`

### Interior Condition
- `NEEDS_GUT`
- `POOR`
- `AVERAGE`
- `NEW_RENO`
- `HIGH_END`

### Workflow Steps
1. `PROPERTY_FACTS`
2. `COMPARABLE_SEARCH`
3. `COMPARABLE_REVIEW`
4. `WEIGHTED_SCORING`
5. `VALUATION_MODELS`
6. `REPORT_GENERATION`

---

## Example Workflow

1. **Start Analysis**
   ```bash
   POST /api/analysis/start
   ```

2. **Update Property Facts** (if needed)
   ```bash
   PUT /api/analysis/{session_id}/step/1
   ```

3. **Advance to Comparable Search**
   ```bash
   POST /api/analysis/{session_id}/step/2
   ```

4. **Review Comparables**
   ```bash
   GET /api/analysis/{session_id}
   ```

5. **Modify Comparables** (if needed)
   ```bash
   PUT /api/analysis/{session_id}/step/3
   ```

6. **Advance through remaining steps**
   ```bash
   POST /api/analysis/{session_id}/step/3
   POST /api/analysis/{session_id}/step/4
   POST /api/analysis/{session_id}/step/5
   POST /api/analysis/{session_id}/step/6
   ```

7. **Generate Report**
   ```bash
   GET /api/analysis/{session_id}/report
   ```

8. **Export to Excel**
   ```bash
   GET /api/analysis/{session_id}/export/excel
   ```
