import React from 'react'
import { Alert, Box, Button, CircularProgress } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import openLetterService from '@/services/openLetterApi'
import { MailBatchSummary } from './MailBatchSummary'
import { MailQueueStagedTable } from './MailQueueStagedTable'

export const MailQueuePanel: React.FC = () => {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['mail-queue'],
    queryFn: () => openLetterService.getQueue(),
    refetchInterval: 15000,
  })

  const errorMessage =
    error instanceof Error ? error.message : 'Failed to load mail queue.'

  if (isLoading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (error && !data) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={() => refetch()} disabled={isFetching}>
            Retry
          </Button>
        }
      >
        {errorMessage}
      </Alert>
    )
  }

  return (
    <Box>
      {error ? (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => refetch()} disabled={isFetching}>
              Retry
            </Button>
          }
        >
          {errorMessage}
        </Alert>
      ) : null}
      <MailBatchSummary title="Mail Queue" queueData={data} />
      <MailQueueStagedTable
        items={data?.items ?? []}
        emptyMessage="No leads in the mail queue. Add leads from property detail or outreach lists."
      />
    </Box>
  )
}
