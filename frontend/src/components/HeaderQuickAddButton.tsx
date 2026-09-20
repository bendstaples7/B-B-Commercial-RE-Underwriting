/**
 * Desktop header plus — opens the same capture flows as the phone Quick Add FAB.
 * Property and lead share one QuickAddPage; contact reuses ContactFormModal.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  IconButton,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import { ContactFormModal } from '@/components/ContactFormModal'

export function HeaderQuickAddButton() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const navigate = useNavigate()
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [contactOpen, setContactOpen] = useState(false)

  if (isMobile) {
    return null
  }

  const closeMenu = () => setAnchorEl(null)

  const openPropertyOrLead = () => {
    closeMenu()
    navigate('/quick-add?kind=property')
  }

  return (
    <>
      <Tooltip title="Add property, lead, or contact">
        <IconButton
          aria-label="Add"
          aria-haspopup="menu"
          aria-expanded={Boolean(anchorEl)}
          data-testid="header-add-button"
          onClick={(event) => setAnchorEl(event.currentTarget)}
          sx={{ cursor: 'pointer' }}
        >
          <AddIcon />
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={closeMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        MenuListProps={{ 'aria-label': 'Add' }}
      >
        <MenuItem
          data-testid="header-add-property-or-lead"
          onClick={openPropertyOrLead}
        >
          <ListItemText
            primary="Property or lead"
            secondary="An address, with source and why"
          />
        </MenuItem>
        <MenuItem
          data-testid="header-add-contact"
          onClick={() => {
            closeMenu()
            setContactOpen(true)
          }}
        >
          <ListItemText
            primary="Contact"
            secondary="A person, with source and why"
          />
        </MenuItem>
      </Menu>
      <ContactFormModal
        open={contactOpen}
        onClose={() => setContactOpen(false)}
        allowLinkExisting={false}
      />
    </>
  )
}
