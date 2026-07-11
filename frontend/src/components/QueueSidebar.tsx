/**
 * QueueSidebar — sidebar navigation with queue links and live badge counts.
 *
 * Polls /api/queues/counts every 5 minutes via React Query (pauses when tab is hidden).
 * Highlights the active queue using useLocation.
 */
import { List, ListItem, ListItemButton, ListItemText, Chip, Box, Typography } from '@mui/material'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { queueService } from '@/services/api'
import type { QueueCounts } from '@/types'

interface QueueLink {
  label: string
  path: string
  badgeKey: keyof QueueCounts | null
}

interface QueueSubgroup {
  label: string
  description: string
  links: QueueLink[]
}

const WORK_QUEUE_SUBGROUPS: QueueSubgroup[] = [
  {
    label: 'Prospecting',
    description: 'Pre-lead discovery from open data',
    links: [
      { label: 'Prospect Review', path: '/queues/prospect-review', badgeKey: 'prospect_candidates' },
    ],
  },
  {
    label: 'Daily outreach',
    description: 'Leads that need attention today',
    links: [
      { label: "Today's Action", path: '/queues/todays-action', badgeKey: 'todays_action' },
      { label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue', badgeKey: 'follow_up_overdue' },
      { label: 'Ready to Mail', path: '/queues/ready-to-mail', badgeKey: 'ready_to_mail' },
    ],
  },
  {
    label: 'Pipeline views',
    description: 'Lead status columns',
    links: [
      { label: 'Kanban', path: '/kanban', badgeKey: null },
    ],
  },
  {
    label: 'Data & review',
    description: 'Fix data and routing gaps',
    links: [
      { label: 'Needs Review', path: '/queues/needs-review', badgeKey: 'needs_review' },
      { label: 'Missing Property Match', path: '/queues/missing-property-match', badgeKey: 'missing_property_match' },
      { label: 'No Next Action', path: '/queues/no-next-action', badgeKey: 'no_next_action' },
    ],
  },
  {
    label: 'History & hold',
    description: 'Lower-frequency and terminal queues',
    links: [
      { label: 'Previously Warm', path: '/queues/previously-warm', badgeKey: 'previously_warm' },
      { label: 'Do Not Contact', path: '/queues/do-not-contact', badgeKey: 'do_not_contact' },
    ],
  },
]

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

      <Box sx={{ px: 2, pt: 0.5, pb: 0.25 }}>
        <Typography
          variant="overline"
          sx={{ fontSize: '0.7rem', letterSpacing: 1, color: 'text.secondary', lineHeight: 1 }}
        >
          Work Queues
        </Typography>
      </Box>

      {WORK_QUEUE_SUBGROUPS.map((group) => (
        <Box key={group.label} data-testid={`queue-group-${group.label.toLowerCase().replace(/\s+/g, '-')}`}>
          <Box sx={{ px: 2, pl: 3, pt: 1, pb: 0.25 }}>
            <Typography
              variant="overline"
              sx={{ fontSize: '0.6rem', letterSpacing: 1, color: 'text.disabled', lineHeight: 1 }}
            >
              {group.label}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.3 }}>
              {group.description}
            </Typography>
          </Box>

          <List disablePadding>
            {group.links.map(({ label, path, badgeKey }) => {
              const isActive = location.pathname === path
              const count = badgeKey ? (counts?.[badgeKey] ?? 0) : 0
              const testId = badgeKey ?? path.replace(/\//g, '-').slice(1)

              return (
                <ListItem key={path} disablePadding>
                  <ListItemButton
                    component={Link}
                    to={path}
                    selected={isActive}
                    data-testid={`queue-link-${testId}`}
                    sx={{
                      pl: 4,
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
                        data-testid={`queue-badge-${testId}`}
                        sx={{ ml: 1, height: 20, fontSize: '0.7rem' }}
                      />
                    )}
                  </ListItemButton>
                </ListItem>
              )
            })}
          </List>
        </Box>
      ))}
    </Box>
  )
}

export default QueueSidebar
