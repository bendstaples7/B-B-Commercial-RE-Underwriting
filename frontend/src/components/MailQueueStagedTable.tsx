import React from 'react'
import {
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import openLetterService, { type MailQueueItem } from '@/services/openLetterApi'
import { formatLastMailedDate, formatLastSaleDate } from '@/utils/formatLastMailedDate'

export interface MailQueueStagedTableProps {
  items: MailQueueItem[]
  emptyMessage?: string
}

export const MailQueueStagedTable: React.FC<MailQueueStagedTableProps> = ({
  items,
  emptyMessage = 'No leads staged for the next batch.',
}) => {
  const queryClient = useQueryClient()

  const removeMutation = useMutation({
    mutationFn: (itemId: number) => openLetterService.removeFromQueue(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      queryClient.invalidateQueries({ queryKey: ['queue-mail-candidates'] })
    },
  })

  return (
    <TableContainer component={Paper} data-testid="mail-queue-staged-table">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Owner</TableCell>
            <TableCell>Property</TableCell>
            <TableCell>Mailing address</TableCell>
            <TableCell>Last mailed</TableCell>
            <TableCell>Last sale</TableCell>
            <TableCell>Added</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} align="center">
                <Typography color="text.secondary" sx={{ py: 3 }}>
                  {emptyMessage}
                </Typography>
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>{item.owner_name || '—'}</TableCell>
                <TableCell>
                  <RouterLink to={`/leads/${item.lead_id}`}>
                    {item.property_street || `#${item.lead_id}`}
                  </RouterLink>
                </TableCell>
                <TableCell>
                  {[item.mailing_address, item.mailing_city, item.mailing_state, item.mailing_zip]
                    .filter(Boolean)
                    .join(', ') || '—'}
                </TableCell>
                <TableCell>{formatLastMailedDate(item.last_mailed_at)}</TableCell>
                <TableCell>{formatLastSaleDate(item.last_sale_at)}</TableCell>
                <TableCell>{formatLastMailedDate(item.created_at)}</TableCell>
                <TableCell align="right">
                  <IconButton
                    size="small"
                    aria-label="Remove from batch"
                    onClick={() => removeMutation.mutate(item.id)}
                    disabled={removeMutation.isPending}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
