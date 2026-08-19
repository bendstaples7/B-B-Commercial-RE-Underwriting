import { useState } from 'react'
import { Box, IconButton, TextField, Typography } from '@mui/material'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { contactService } from '@/services/api'
import { splitDisplayName } from '@/utils/propertyContacts'
import { AppSnackbar } from '@/components/AppSnackbar'
import { ccRowTitleSx } from '@/components/lead-detail/commandCenterChrome'

export interface ContactNameInlineEditProps {
  contactId: number
  displayName: string
  leadId: number
  titleSx?: object
  isPrimary?: boolean
  inputTestId: string
  editButtonTestId: string
  displayNameTestId?: string
}

export function ContactNameInlineEdit({
  contactId,
  displayName,
  leadId,
  titleSx,
  isPrimary = false,
  inputTestId,
  editButtonTestId,
  displayNameTestId,
}: ContactNameInlineEditProps) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(displayName)
  const [snack, setSnack] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  })

  const saveMutation = useMutation({
    mutationFn: async (name: string) => {
      const parts = splitDisplayName(name)
      await contactService.updateContact(contactId, parts)
    },
    onSuccess: () => {
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', leadId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      setSnack({ open: true, message: 'Name updated.', severity: 'success' })
    },
    onError: (err: Error) => {
      setSnack({ open: true, message: err.message || 'Failed to update name.', severity: 'error' })
    },
  })

  if (editing) {
    return (
      <>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', width: '100%' }}>
          <TextField
            size="small"
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
            inputProps={{
              'data-testid': inputTestId,
              style: { cursor: 'text' },
            }}
            sx={{ caretColor: 'text.primary' }}
          />
          <IconButton
            size="small"
            color="primary"
            aria-label="Save name"
            disabled={!value.trim() || saveMutation.isPending}
            onClick={() => saveMutation.mutate(value.trim())}
          >
            <CheckIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            aria-label="Cancel edit"
            onClick={() => {
              setEditing(false)
              setValue(displayName)
            }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
        <AppSnackbar
          open={snack.open}
          message={snack.message}
          severity={snack.severity}
          onClose={() => setSnack((s) => ({ ...s, open: false }))}
        />
      </>
    )
  }

  return (
    <>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, width: '100%' }}>
        <Typography
          sx={{ ...ccRowTitleSx, fontWeight: isPrimary ? 600 : 400, minWidth: 0, ...titleSx }}
          data-testid={displayNameTestId}
        >
          {displayName}
        </Typography>
        <IconButton
          size="small"
          aria-label={`Edit ${displayName}`}
          onClick={() => {
            setValue(displayName)
            setEditing(true)
          }}
          data-testid={editButtonTestId}
        >
          <EditOutlinedIcon fontSize="small" />
        </IconButton>
      </Box>
      <AppSnackbar
        open={snack.open}
        message={snack.message}
        severity={snack.severity}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
      />
    </>
  )
}
