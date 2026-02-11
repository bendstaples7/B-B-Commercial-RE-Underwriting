# React Components - Report and Scenario Analysis

This directory contains the React components for Step 6 (Report Display) and Scenario Analysis functionality.

## Components Overview

### ReportDisplay Component
**File:** `ReportDisplay.tsx`

Displays the complete analysis report with all 6 sections:
- Section A: Subject Property Facts
- Section B: Comparable Sales
- Section C: Weighted Ranking
- Section D: Valuation Models (with narratives and adjustments)
- Section E: Final ARV Range (conservative, likely, aggressive)
- Section F: Key Drivers

**Features:**
- Export to Excel functionality
- Export to Google Sheets functionality
- Formatted tables with proper styling
- Currency and date formatting

**Props:**
```typescript
interface ReportDisplayProps {
  report: Report
  sessionId: string
}
```

**Usage:**
```tsx
import { ReportDisplay } from '@/components/ReportDisplay'

<ReportDisplay report={report} sessionId={sessionId} />
```

---

### ScenarioAnalysisPanel Component
**File:** `ScenarioAnalysisPanel.tsx`

Main container for scenario analysis with checkboxes to select scenarios:
- Wholesale Strategy
- Fix & Flip Strategy
- Buy & Hold Strategy

Displays scenario comparison table when multiple scenarios are selected.

**Props:**
```typescript
interface ScenarioAnalysisPanelProps {
  arvRange: ARVRange
  sessionId: string
  onScenariosChange?: (scenarios: Scenario[]) => void
}
```

**Usage:**
```tsx
import { ScenarioAnalysisPanel } from '@/components/ScenarioAnalysisPanel'

<ScenarioAnalysisPanel 
  arvRange={arvRange} 
  sessionId={sessionId}
  onScenariosChange={(scenarios) => console.log(scenarios)}
/>
```

---

### WholesaleScenarioForm Component
**File:** `WholesaleScenarioForm.tsx`

Calculates wholesale investment analysis:
- Maximum Allowable Offer (MAO)
- Contract Price
- Assignment Fee Range

**Formula:**
- MAO = Conservative ARV × 70% - Estimated Repairs
- Contract Price = MAO × 95%
- Assignment Fee = Contract Price × 5-10%

**Props:**
```typescript
interface WholesaleScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: WholesaleScenario) => void
}
```

---

### FixFlipScenarioForm Component
**File:** `FixFlipScenarioForm.tsx`

Calculates fix and flip investment analysis with complete cost breakdown:
- Acquisition Cost
- Renovation Cost
- Holding Costs (2% per month)
- Financing Costs (11% interest, 75% LTC)
- Closing Costs (8% of ARV)
- Net Profit and ROI

**Props:**
```typescript
interface FixFlipScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: FixFlipScenario) => void
}
```

---

### BuyHoldScenarioForm Component
**File:** `BuyHoldScenarioForm.tsx`

Calculates buy and hold investment analysis with dual capital structures:
1. 5% Down Owner-Occupied (6.5% interest)
2. 25% Down Investor (7.5% interest)

Generates price point analysis (low, medium, high) with:
- Monthly Cash Flow
- Cash-on-Cash Return
- Cap Rate

**Props:**
```typescript
interface BuyHoldScenarioFormProps {
  arvRange: ARVRange
  onScenarioUpdate: (scenario: BuyHoldScenario) => void
}
```

---

### ScenarioComparisonTable Component
**File:** `ScenarioComparisonTable.tsx`

Displays side-by-side comparison of all selected scenarios:
- Shows ROI and profit for each scenario
- Highlights highest ROI strategy for each price point
- Displays comparison across low, medium, and high price points

**Props:**
```typescript
interface ScenarioComparisonTableProps {
  scenarios: Scenario[]
}
```

---

## Integration Example

Here's how to integrate these components into a workflow step:

```tsx
import React, { useState } from 'react'
import { Box, Divider } from '@mui/material'
import { ReportDisplay } from '@/components/ReportDisplay'
import { ScenarioAnalysisPanel } from '@/components/ScenarioAnalysisPanel'
import type { Report, Scenario } from '@/types'

interface Step6Props {
  report: Report
  sessionId: string
}

export const Step6: React.FC<Step6Props> = ({ report, sessionId }) => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])

  return (
    <Box>
      {/* Display the main report */}
      <ReportDisplay report={report} sessionId={sessionId} />
      
      <Divider sx={{ my: 4 }} />
      
      {/* Optional scenario analysis */}
      {report.valuationResult && (
        <ScenarioAnalysisPanel
          arvRange={report.valuationResult.arvRange}
          sessionId={sessionId}
          onScenariosChange={setScenarios}
        />
      )}
    </Box>
  )
}
```

## Requirements Validation

These components satisfy the following requirements:

### Task 17.1 - ReportDisplay Component
- ✅ Display all 6 report sections (A-F)
- ✅ Add "Export to Excel" button
- ✅ Add "Export to Google Sheets" button
- ✅ Handle export downloads and links
- ✅ Requirements: 6.1-6.8

### Task 17.2 - ScenarioAnalysisPanel Component
- ✅ Add scenario selection checkboxes (wholesale, fix & flip, buy & hold)
- ✅ Create WholesaleScenarioForm with inputs and results display
- ✅ Create FixFlipScenarioForm with renovation budget input and results
- ✅ Create BuyHoldScenarioForm with rent input and dual capital structure results
- ✅ Display scenario comparison table when multiple scenarios selected
- ✅ Highlight highest ROI strategies
- ✅ Requirements: 7.1-10.5

## Testing

Unit tests for these components should cover:
- Component rendering
- User interactions (checkbox selection, form inputs)
- Calculation accuracy
- Export button functionality
- Scenario comparison logic
- ROI highlighting

## Notes

- All currency values are formatted using `Intl.NumberFormat`
- All calculations follow the formulas specified in the design document
- Components use Material-UI for consistent styling
- Export functionality integrates with the backend API service
- Scenario calculations update in real-time as inputs change
