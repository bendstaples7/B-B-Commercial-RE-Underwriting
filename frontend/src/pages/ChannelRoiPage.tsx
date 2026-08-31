import React, { useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputAdornment,
  Link as MuiLink,
  Paper,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import channelRoiService, {
  type ChannelCampaignRow,
  type ChannelSummary,
} from '@/services/channelRoiApi'

const headerCellSx = {
  fontWeight: 600,
  color: 'text.secondary',
  fontSize: '0.75rem',
  letterSpacing: 0.02,
  py: 0.75,
  px: 1,
} as const

const bodyCellSx = {
  fontWeight: 400,
  color: 'text.primary',
  fontSize: '0.75rem',
  py: 0.75,
  px: 1,
  lineHeight: 1.35,
} as const

function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(n)
}

function moneyExact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(n)
}

function pct(rate: number | null | undefined): string {
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(2)}%`
}

function roiX(
  n: number | null | undefined,
  knobsSet: boolean,
  opts?: { onSetAssumptions?: () => void; canEditAssumptions?: boolean },
) {
  if (!knobsSet) {
    if (opts?.canEditAssumptions && opts.onSetAssumptions) {
      return (
        <MuiLink
          component="button"
          type="button"
          variant="body2"
          onClick={opts.onSetAssumptions}
          sx={{ cursor: 'pointer', fontSize: '0.75rem' }}
        >
          Set assumptions
        </MuiLink>
      )
    }
    return (
      <Typography component="span" variant="body2" color="text.secondary" sx={{ fontSize: '0.75rem' }}>
        Ask an admin
      </Typography>
    )
  }
  if (n == null) return '—'
  return `${n.toFixed(2)}×`
}

function ChannelHalf({
  title,
  summary,
  knobsSet,
  emptyHint,
  onSetAssumptions,
  canEditAssumptions,
}: {
  title: string
  summary: ChannelSummary
  knobsSet: boolean
  emptyHint?: React.ReactNode
  onSetAssumptions?: () => void
  canEditAssumptions?: boolean
}) {
  if (emptyHint) {
    return (
      <Box sx={{ flex: 1, minWidth: 0, p: 1.5 }}>
        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, letterSpacing: 0.04 }}>
          {title}
        </Typography>
        {emptyHint}
      </Box>
    )
  }
  return (
    <Box sx={{ flex: 1, minWidth: 0, p: 1.5 }}>
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, letterSpacing: 0.04 }}>
        {title}
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 1,
          rowGap: 1.25,
        }}
      >
        <Box>
          <Typography variant="caption" color="text.secondary">
            Spend
          </Typography>
          <Typography variant="body1" fontWeight={600}>
            {money(summary.spend)}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">
            Responses
          </Typography>
          <Typography variant="body1" fontWeight={600}>
            {summary.responses}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">
            Cost / response
          </Typography>
          <Typography variant="body1" fontWeight={600}>
            {moneyExact(summary.cost_per_response)}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">
            Proj. ROI
          </Typography>
          <Typography variant="body1" fontWeight={600} component="div">
            {roiX(summary.projected_roi, knobsSet, { onSetAssumptions, canEditAssumptions })}
          </Typography>
        </Box>
        {summary.response_rate != null && (
          <Box sx={{ gridColumn: '1 / -1' }}>
            <Typography variant="caption" color="text.secondary">
              Response rate
              {summary.denominator_label ? ` (${summary.denominator_label})` : ''}
            </Typography>
            <Typography variant="body2">{pct(summary.response_rate)}</Typography>
          </Box>
        )}
      </Box>
    </Box>
  )
}

function CampaignTable({
  rows,
  knobsSet,
  emptyMessage,
  onSetAssumptions,
  canEditAssumptions,
}: {
  rows: ChannelCampaignRow[]
  knobsSet: boolean
  emptyMessage: React.ReactNode
  onSetAssumptions?: () => void
  canEditAssumptions?: boolean
}) {
  if (rows.length === 0) {
    return (
      <Box sx={{ py: 3, px: 1 }}>
        <Typography variant="body2" color="text.secondary">
          {emptyMessage}
        </Typography>
      </Box>
    )
  }
  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell sx={headerCellSx}>Name</TableCell>
            <TableCell sx={headerCellSx} align="right">
              Spend
            </TableCell>
            <TableCell sx={headerCellSx} align="right">
              Denom.
            </TableCell>
            <TableCell sx={headerCellSx} align="right">
              Responses
            </TableCell>
            <TableCell sx={headerCellSx} align="right">
              Rate
            </TableCell>
            <TableCell sx={headerCellSx} align="right">
              Cost / resp.
            </TableCell>
            <TableCell sx={headerCellSx} align="right">
              Proj. ROI
            </TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} hover>
              <TableCell sx={bodyCellSx}>{r.name}</TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {moneyExact(r.spend)}
              </TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {r.denominator != null ? r.denominator.toLocaleString() : '—'}
              </TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {r.responses}
              </TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {pct(r.response_rate)}
              </TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {moneyExact(r.cost_per_response)}
              </TableCell>
              <TableCell sx={bodyCellSx} align="right">
                {roiX(r.projected_roi, knobsSet, { onSetAssumptions, canEditAssumptions })}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export const ChannelRoiPage: React.FC = () => {
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin)
  const queryClient = useQueryClient()
  const settingsRef = useRef<HTMLDivElement>(null)
  const [tab, setTab] = useState(0)
  const [profit, setProfit] = useState('')
  const [closeRate, setCloseRate] = useState('')
  const [adAccount, setAdAccount] = useState('')
  const [token, setToken] = useState('')
  const [settingsHydrated, setSettingsHydrated] = useState(false)

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['channel-roi'],
    queryFn: () => channelRoiService.getDashboard(),
  })

  React.useEffect(() => {
    if (!data || settingsHydrated) return
    const s = data.settings
    setProfit(s.expected_profit_per_deal != null ? String(s.expected_profit_per_deal) : '')
    setCloseRate(
      s.assumed_close_rate != null ? String(Number((s.assumed_close_rate * 100).toFixed(2))) : '',
    )
    setAdAccount(s.meta_ad_account_id ?? '')
    setSettingsHydrated(true)
  }, [data, settingsHydrated])

  const saveMutation = useMutation({
    mutationFn: () =>
      channelRoiService.patchSettings({
        expected_profit_per_deal: profit === '' ? undefined : Number(profit),
        assumed_close_rate: closeRate === '' ? undefined : Number(closeRate),
        meta_ad_account_id: adAccount,
        meta_access_token: token.trim() ? token.trim() : undefined,
      }),
    onSuccess: async () => {
      setToken('')
      setSettingsHydrated(false)
      await queryClient.invalidateQueries({ queryKey: ['channel-roi'] })
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => channelRoiService.syncFacebook(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['channel-roi'] })
      await queryClient.invalidateQueries({ queryKey: ['facebook-campaigns-for-attribution'] })
    },
  })

  const focusSettings = () => {
    settingsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const knobsSet = Boolean(data?.projection_knobs_set)
  const settings = data?.settings

  const fbEmptyHint = useMemo(() => {
    if (!settings) return null
    if (settings.meta_connected) {
      return (
        <Typography variant="body2" color="text.secondary">
          No Facebook campaigns synced yet.
          {isAdmin ? ' Use Refresh below to pull from Meta.' : ''}
        </Typography>
      )
    }
    if (isAdmin) {
      return (
        <Typography variant="body2" color="text.secondary">
          Meta not connected.{' '}
          <MuiLink component="button" type="button" onClick={focusSettings} sx={{ cursor: 'pointer' }}>
            Connect Meta ad account
          </MuiLink>
        </Typography>
      )
    }
    return (
      <Typography variant="body2" color="text.secondary">
        Not connected
      </Typography>
    )
  }, [settings, isAdmin])

  return (
    <Box
      component="main"
      sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
      data-testid="channel-roi-page"
    >
      <Typography variant="h5" component="h1" gutterBottom data-testid="channel-roi-title">
        Channel ROI
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Spend → responses → projected return
      </Typography>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }} data-testid="channel-roi-loading">
          <CircularProgress size={32} />
        </Box>
      )}

      {isError && (
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => refetch()}>
              Retry
            </Button>
          }
          sx={{ mb: 2 }}
        >
          Couldn&apos;t load Channel ROI
        </Alert>
      )}

      {data && (
        <>
          <Paper
            variant="outlined"
            sx={{
              display: 'flex',
              flexDirection: { xs: 'column', md: 'row' },
              divide: 'none',
              mb: 2,
              overflow: 'hidden',
            }}
            data-testid="channel-roi-rollup"
          >
            <ChannelHalf
              title="DIRECT MAIL"
              summary={data.channels.direct_mail}
              knobsSet={knobsSet}
              onSetAssumptions={focusSettings}
              canEditAssumptions={isAdmin}
              emptyHint={
                data.direct_mail_campaigns.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    No mail batches yet.{' '}
                    <MuiLink component={RouterLink} to="/marketing/direct-mail/batches">
                      Open Mail Batches
                    </MuiLink>
                  </Typography>
                ) : undefined
              }
            />
            <Box
              sx={{
                width: { xs: '100%', md: '1px' },
                height: { xs: '1px', md: 'auto' },
                bgcolor: 'divider',
                flexShrink: 0,
              }}
            />
            <ChannelHalf
              title="FACEBOOK"
              summary={data.channels.facebook}
              knobsSet={knobsSet}
              onSetAssumptions={focusSettings}
              canEditAssumptions={isAdmin}
              emptyHint={
                !data.settings.meta_connected || data.facebook_campaigns.length === 0
                  ? fbEmptyHint
                  : undefined
              }
            />
          </Paper>

          <Paper variant="outlined" sx={{ mb: 2 }} data-testid="channel-roi-breakdowns">
            <Tabs
              value={tab}
              onChange={(_e, v: number) => setTab(v)}
              sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}
            >
              <Tab label="Direct mail" />
              <Tab label="Facebook" />
            </Tabs>
            <Box sx={{ p: 0.5 }}>
              {tab === 0 && (
                <CampaignTable
                  rows={data.direct_mail_campaigns}
                  knobsSet={knobsSet}
                  onSetAssumptions={focusSettings}
                  canEditAssumptions={isAdmin}
                  emptyMessage={
                    <>
                      No mailers yet. Send a batch from{' '}
                      <MuiLink component={RouterLink} to="/queues/ready-to-mail">
                        Ready to Mail
                      </MuiLink>
                      .
                    </>
                  }
                />
              )}
              {tab === 1 && (
                <CampaignTable
                  rows={data.facebook_campaigns}
                  knobsSet={knobsSet}
                  onSetAssumptions={focusSettings}
                  canEditAssumptions={isAdmin}
                  emptyMessage={fbEmptyHint ?? 'No Facebook campaigns yet.'}
                />
              )}
            </Box>
          </Paper>

          {isAdmin && (
            <Paper
              variant="outlined"
              sx={{ p: 1.5 }}
              ref={settingsRef}
              data-testid="channel-roi-settings"
              component="section"
              aria-label="Assumptions and Meta"
            >
              <Box
                sx={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 1,
                  mb: 1.5,
                }}
              >
                <Typography variant="subtitle2">Assumptions & Meta</Typography>
                <Typography variant="caption" color="text.secondary">
                  {settings?.last_synced_at
                    ? `Last synced ${new Date(settings.last_synced_at).toLocaleString()}`
                    : 'Never synced'}
                  {isFetching || syncMutation.isPending ? ' · refreshing…' : ''}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                Meta setup: Business Manager → System user → generate a Marketing API token with ads
                read access → paste the ad account id (act_…) and token below.
              </Typography>
              {settings?.last_sync_error && (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  {settings.last_sync_error}
                </Alert>
              )}
              {saveMutation.isError && (
                <Alert severity="error" sx={{ mb: 1.5 }}>
                  {saveMutation.error instanceof Error
                    ? saveMutation.error.message
                    : 'Failed to save settings'}
                </Alert>
              )}
              {syncMutation.isError && (
                <Alert severity="error" sx={{ mb: 1.5 }}>
                  {syncMutation.error instanceof Error
                    ? syncMutation.error.message
                    : 'Meta sync failed'}
                </Alert>
              )}
              <Box
                sx={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 1.5,
                  alignItems: 'flex-start',
                }}
              >
                <TextField
                  label="Expected profit / deal"
                  size="small"
                  value={profit}
                  onChange={(e) => setProfit(e.target.value)}
                  InputProps={{
                    startAdornment: <InputAdornment position="start">$</InputAdornment>,
                  }}
                  sx={{ width: { xs: '100%', sm: 180 } }}
                />
                <TextField
                  label="Close rate %"
                  size="small"
                  value={closeRate}
                  onChange={(e) => setCloseRate(e.target.value)}
                  sx={{ width: { xs: '100%', sm: 140 } }}
                />
                <TextField
                  label="Meta ad account id"
                  size="small"
                  value={adAccount}
                  onChange={(e) => setAdAccount(e.target.value)}
                  placeholder="act_123…"
                  sx={{ width: { xs: '100%', sm: 200 } }}
                />
                <TextField
                  label="Meta access token"
                  size="small"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder={settings?.has_meta_token ? '•••• saved — paste to replace' : 'Paste token'}
                  sx={{ width: { xs: '100%', sm: 260 } }}
                />
                <FormControl sx={{ flexDirection: 'row', gap: 1 }}>
                  <Button
                    variant="contained"
                    size="small"
                    disabled={saveMutation.isPending}
                    onClick={() => saveMutation.mutate()}
                  >
                    {saveMutation.isPending ? 'Saving…' : 'Save'}
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={
                      syncMutation.isPending ? <CircularProgress size={14} /> : <RefreshIcon />
                    }
                    disabled={syncMutation.isPending || !settings?.meta_connected}
                    onClick={() => syncMutation.mutate()}
                  >
                    Refresh
                  </Button>
                </FormControl>
              </Box>
            </Paper>
          )}
        </>
      )}
    </Box>
  )
}

export default ChannelRoiPage
