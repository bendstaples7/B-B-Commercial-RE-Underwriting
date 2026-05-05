import React, { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Chip,
  CircularProgress,
  Alert,
  Pagination,
  Collapse,
  Button,
  IconButton,
} from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import ReplayIcon from '@mui/icons-material/Replay'
import type { ImportJob, ImportJobListResponse } from '@/types'
import { ImportJobStatus } from '@/types'
import { leadService } from '@/services/leadApi'

/** Props accepted by ImportHistoryTable. */
export interface ImportHistoryTableProps {
  /** Called when a re-run starts a new import job. */
  onImportStarted?: (job: ImportJob) => void
}

const PER_PAGE = 10

/** Map ImportJobStatus to MUI Chip color. */
function getStatusColor(
  status: ImportJobStatus,
): 'default' | 'info' | 'success' | 'error' {
  switch (status) {
    case ImportJobStatus.PENDING:
      return 'default'
    case ImportJobStatus.IN_PROGRESS:
      return 'info'
    case ImportJobStatus.COMPLETED:
      return 'success'
    case ImportJobStatus.FAILED:
      return 'error'
    default:
      return 'default'
  }
}

/** Format an ISO date string for display. */
function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return '—'
  }
}

/**
 * Table of past imports with status, timestamps, row counts, error detail, and re-run action.
 *
 * Requirements: 8.1, 8.2, 8.3
 */
export const ImportHistoryTable: React.FC<ImportHistoryTableProps> = ({
  onImportStarted,
}) => {
  const [jobs, setJobs] = useState<ImportJob[]>([])
  const [totalJobs, setTotalJobs] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Track which rows are expanded to show error logs
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

  // Track which jobs are currently being re-run
  const [rerunningJobs, setRerunningJobs] = useState<Set<number>>(new Set())

  const fetchJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response: ImportJobListResponse = await leadService.listImportJobs({
        page,
        per_page: PER_PAGE,
      })
      setJobs(response.jobs)
      setTotalJobs(response.total)
      setTotalPages(response.pages)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to load import history.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  const toggleRow = (jobId: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(jobId)) {
        next.delete(jobId)
      } else {
        next.add(jobId)
      }
      return next
    })
  }

  const handleRerun = async (jobId: number) => {
    setRerunningJobs((prev) => new Set(prev).add(jobId))
    try {
      const newJob = await leadService.rerunImport(jobId)
      onImportStarted?.(newJob)
      // Refresh the table to show the new job
      await fetchJobs()
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to re-run import.'
      setError(message)
    } finally {
      setRerunningJobs((prev) => {
        const next = new Set(prev)
        next.delete(jobId)
        return next
      })
    }
  }

  return (
    <Box
      component="section"
      aria-labelledby="import-history-heading"
      sx={{ px: { xs: 1, sm: 2 } }}
    >
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5" id="import-history-heading" component="h2">
          Import History
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {totalJobs} import{totalJobs !== 1 ? 's' : ''} found
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {error}
        </Alert>
      )}

      <TableContainer
        component={Paper}
        sx={{ overflowX: 'auto' }}
        role="region"
        aria-labelledby="import-history-heading"
      >
        <Table size="small" aria-label="Import history table">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 48 }} scope="col" />
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Spreadsheet ID
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Sheet Name
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="center" scope="col">
                Status
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Started At
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                Completed At
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Total Rows
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Imported
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="right" scope="col">
                Skipped
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold' }} align="center" scope="col">
                Actions
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && jobs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center" sx={{ py: 6 }}>
                  <CircularProgress size={32} aria-label="Loading import history" />
                </TableCell>
              </TableRow>
            ) : jobs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center" sx={{ py: 6 }}>
                  <Typography variant="body2" color="text.secondary">
                    No imports found. Use the Import Wizard to import leads from Google Sheets.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              jobs.map((job) => {
                const isExpanded = expandedRows.has(job.id)
                const isRerunning = rerunningJobs.has(job.id)
                const hasErrors =
                  job.error_log && job.error_log.length > 0

                return (
                  <React.Fragment key={job.id}>
                    <TableRow
                      hover
                      aria-label={`Import job ${job.id}: ${job.sheet_name}, status ${job.status}`}
                    >
                      <TableCell>
                        {hasErrors && (
                          <IconButton
                            size="small"
                            onClick={() => toggleRow(job.id)}
                            aria-label={
                              isExpanded
                                ? `Collapse error log for job ${job.id}`
                                : `Expand error log for job ${job.id}`
                            }
                            aria-expanded={isExpanded}
                          >
                            {isExpanded ? (
                              <KeyboardArrowUpIcon />
                            ) : (
                              <KeyboardArrowDownIcon />
                            )}
                          </IconButton>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={job.spreadsheet_id}>
                          {job.spreadsheet_id}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">{job.sheet_name}</Typography>
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          label={job.status}
                          size="small"
                          color={getStatusColor(job.status)}
                          aria-label={`Status: ${job.status}`}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {formatDate(job.started_at)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {formatDate(job.completed_at)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2">{job.total_rows}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2">{job.rows_imported}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2">{job.rows_skipped}</Typography>
                      </TableCell>
                      <TableCell align="center">
                        {job.status === ImportJobStatus.COMPLETED && (
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={
                              isRerunning ? (
                                <CircularProgress size={16} />
                              ) : (
                                <ReplayIcon />
                              )
                            }
                            onClick={() => handleRerun(job.id)}
                            disabled={isRerunning}
                            aria-label={`Re-run import job ${job.id}`}
                          >
                            Re-run
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>

                    {/* Expandable error log row */}
                    {hasErrors && (
                      <TableRow>
                        <TableCell
                          colSpan={10}
                          sx={{ py: 0, borderBottom: isExpanded ? undefined : 'none' }}
                        >
                          <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                            <Box
                              sx={{ py: 2, px: 2 }}
                              role="region"
                              aria-label={`Error log for import job ${job.id}`}
                            >
                              <Typography
                                variant="subtitle2"
                                gutterBottom
                                component="h3"
                              >
                                Error Log ({job.error_log.length} error
                                {job.error_log.length !== 1 ? 's' : ''})
                              </Typography>
                              <Table size="small" aria-label={`Errors for job ${job.id}`}>
                                <TableHead>
                                  <TableRow>
                                    <TableCell sx={{ fontWeight: 'bold', width: 100 }} scope="col">
                                      Row
                                    </TableCell>
                                    <TableCell sx={{ fontWeight: 'bold' }} scope="col">
                                      Error
                                    </TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {job.error_log.map((entry, idx) => (
                                    <TableRow key={idx}>
                                      <TableCell>{entry.row}</TableCell>
                                      <TableCell>{entry.error}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {totalPages > 1 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
          <Pagination
            count={totalPages}
            page={page}
            onChange={(_e, value) => setPage(value)}
            color="primary"
            showFirstButton
            showLastButton
            aria-label="Import history pagination"
          />
        </Box>
      )}
    </Box>
  )
}
