import React, { useState } from 'react'
import {
  Box,
  Typography,
  Button,
  Alert,
  CircularProgress,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import DownloadIcon from '@mui/icons-material/Download'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { condoFilterService } from '@/services/condoFilterApi'
import { CondoResultsTable } from './CondoResultsTable'
import { CondoDetailView } from './CondoDetailView'
import type { AddressGroupAnalysis, CondoFilterParams, CondoAnalysisSummary } from '@/types'

export const CondoReviewPage: React.FC = () => {
  const queryClient = useQueryClient()

  // Filter and pagination state
  const [filters, setFilters] = useState<CondoFilterParams>({ page: 1, per_page: 20 })

  // Detail view state
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<number | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // Analysis summary after run
  const [summary, setSummary] = useState<CondoAnalysisSummary | null>(null)

  // Run analysis mutation
  const analysisMutation = useMutation({
    mutationFn: () => condoFilterService.runAnalysis(),
    onSuccess: (data) => {
      setSummary(data)
      queryClient.invalidateQueries({ queryKey: ['condoFilterResults'] })
    },
  })

  // CSV export state
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const handleRunAnalysis = () => {
    setSummary(null)
    analysisMutation.mutate()
  }

  const handleExportCsv = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const blob = await condoFilterService.exportCsv(filters)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'condo_filter_results.csv'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Failed to export CSV.')
    } finally {
      setExporting(false)
    }
  }

  const handleRowClick = (analysis: AddressGroupAnalysis) => {
    setSelectedAnalysisId(analysis.id)
    setDetailOpen(true)
  }

  const handleDetailClose = () => {
    setDetailOpen(false)
    setSelectedAnalysisId(null)
  }

  return (
    <Box component="section" aria-labelledby="condo-review-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      {/* Page Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Typography variant="h5" id="condo-review-heading" component="h2">
          Condo Filter
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="contained"
            startIcon={analysisMutation.isPending ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
            onClick={handleRunAnalysis}
            disabled={analysisMutation.isPending}
          >
            {analysisMutation.isPending ? 'Running...' : 'Run Analysis'}
          </Button>
          <Button
            variant="outlined"
            startIcon={exporting ? <CircularProgress size={16} /> : <DownloadIcon />}
            onClick={handleExportCsv}
            disabled={exporting}
          >
            {exporting ? 'Exporting...' : 'Export CSV'}
          </Button>
        </Box>
      </Box>

      {/* Analysis Error */}
      {analysisMutation.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {analysisMutation.error instanceof Error
            ? analysisMutation.error.message
            : 'Analysis failed.'}
        </Alert>
      )}

      {/* Export Error */}
      {exportError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setExportError(null)}>
          {exportError}
        </Alert>
      )}

      {/* Analysis Summary */}
      {summary && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Analysis complete: {summary.total_groups} address groups, {summary.total_properties} properties processed.
        </Alert>
      )}

      {/* Results Table */}
      <CondoResultsTable
        filters={filters}
        onFiltersChange={setFilters}
        onRowClick={handleRowClick}
      />

      {/* Detail Drawer */}
      <CondoDetailView
        analysisId={selectedAnalysisId}
        open={detailOpen}
        onClose={handleDetailClose}
      />
    </Box>
  )
}
