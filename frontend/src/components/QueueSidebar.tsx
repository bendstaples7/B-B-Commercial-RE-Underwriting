/**
 * QueueSidebar — sidebar navigation with queue links and live badge counts.
 *
 * Polls /api/queues/counts every 5 minutes via React Query (pauses when tab is hidden).
 * Highlights the active queue using useLocation.
 *
 * Requirements: 18.1, 18.2
 */
import { List, ListItem, ListItemButton, ListItemText, Chip, Box, Typography } from '@mui/material'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { queueService } from '@/services/api'
import type { QueueCounts } from '@/types'

// ---------------------------------------------------------------------------
// Queue link definitions
// ---------------------------------------------------------------------------

interface QueueLink {
  label: string
  path: string
  badgeKey: keyof QueueCounts
}

const QUEUE_LINKS: QueueLink[] = [
  { label: 'Ready to Mail',          path: '/queues/ready-to-mail',          badgeKey: 'ready_to_mail' },
  { label: "Today's Action",         path: '/queues/todays-action',          badgeKey: 'todays_action' },
  { label: 'Previously Warm',        path: '/queues/previously-warm',        badgeKey: 'previously_warm' },
  { label: 'Follow-Up Overdue',      path: '/queues/follow-up-overdue',      badgeKey: 'follow_up_overdue' },
  { label: 'No Next Action',         path: '/queues/no-next-action',         badgeKey: 'no_next_action' },
  { label: 'Needs Review',           path: '/queues/needs-review',           badgeKey: 'needs_review' },
  { label: 'Do Not Contact',         path: '/queues/do-not-contact',         badgeKey: 'do_not_contact' },
  { label: 'Missing Property Match', path: '/queues/missing-property-match', badgeKey: 'missing_property_match' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * QueueSidebar renders a vertical nav list of CRM work queues.
 * Badge counts are fetched from the API and refreshed every 5 minutes (paused when tab is hidden).
 * The currently active queue is highlighted based on the current URL path.
 */
export function QueueSidebar() {
  const location = useLocation()

  const { data: counts } = useQuery<QueueCounts>({
    queryKey: ['queue-counts'],
    queryFn: () => queueService.getCounts(),
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  })

  return (
    <Box
      component="nav"
      aria-label="Queue navigation"
      data-testid="queue-sidebar"
      sx={{ width: 240, flexShrink: 0 }}
    >
      <Typography
        variant="overline"
        sx={{ px: 2, pt: 2, pb: 0.5, display: 'block', color: 'text.secondary' }}
      >
        Queues
      </Typography>

      <List disablePadding>
        {QUEUE_LINKS.map(({ label, path, badgeKey }) => {
          const isActive = location.pathname === path
          const count = counts?.[badgeKey] ?? 0

          return (
            <ListItem key={path} disablePadding>
              <ListItemButton
                component={Link}
                to={path}
                selected={isActive}
                data-testid={`queue-link-${badgeKey}`}
                sx={{
                  borderRadius: 1,
                  mx: 0.5,
                  '&.Mui-selected': {
                    bgcolor: 'primary.main',
                    color: 'primary.contrastText',
                    '&:hover': { bgcolor: 'primary.dark' },
                  },
                }}
              >
                <ListItemText
                  primary={label}
                  primaryTypographyProps={{ variant: 'body2', noWrap: true }}
                />
                {count > 0 && (
                  <Chip
                    label={count}
                    size="small"
                    color={isActive ? 'default' : 'primary'}
                    data-testid={`queue-badge-${badgeKey}`}
                    sx={{ ml: 1, height: 20, fontSize: '0.7rem' }}
                  />
                )}
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>
    </Box>
  )
}

export default QueueSidebar
