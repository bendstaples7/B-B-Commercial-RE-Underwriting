/**
 * Desktop header plus — opens Quick Add, the same capture as the phone FAB.
 * A property and its contacts are one form; lead detail still uses ContactFormModal.
 */
import { useNavigate } from 'react-router-dom'
import { IconButton, Tooltip, useMediaQuery, useTheme } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'

export function HeaderQuickAddButton() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const navigate = useNavigate()

  if (isMobile) {
    return null
  }

  return (
    <Tooltip title="Add a property and its contacts">
      <IconButton
        aria-label="Add a property"
        data-testid="header-add-button"
        onClick={() => navigate('/quick-add')}
        sx={{ cursor: 'pointer' }}
      >
        <AddIcon />
      </IconButton>
    </Tooltip>
  )
}
