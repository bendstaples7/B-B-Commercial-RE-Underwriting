import React, { useEffect, useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import openLetterService, { type MailCreativePreset } from '@/services/openLetterApi'
import {
  extractOlcListRows,
  getDirectMailSetupSteps,
  isDirectMailReadyToSend,
} from '@/utils/directMailSetup'
import { formatPhoneNumber } from '@/utils/phone'
import {
  describeOlcProduct,
  findOlcProductForEnvelope,
  formatOlcProductLabel,
  listOlcEnvelopeTypes,
  OLC_PRICING_URL,
  POSTAGE_COMPARISON,
  sortOlcProducts,
  type OlcProduct,
} from '@/utils/olcProductHelpers'

const OLC_TEMPLATE_URL = 'https://app.openletterconnect.com/'

const EMPTY_RETURN_ADDRESS = {
  address1: '',
  address2: '',
  city: '',
  state: '',
  zip: '',
}

function newPreset(partial?: Partial<MailCreativePreset>): MailCreativePreset {
  const id = partial?.id || (typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `preset-${Date.now()}`)
  return {
    id,
    label: partial?.label || 'New creative',
    first_name: partial?.first_name || '',
    last_name: partial?.last_name || '',
    phone: partial?.phone ? formatPhoneNumber(partial.phone) : '',
    email: partial?.email || '',
    website: partial?.website || '',
    include_email: partial?.include_email ?? false,
    include_website: partial?.include_website ?? false,
    envelope_color: partial?.envelope_color || '',
    font_name: partial?.font_name || '',
    font_color: partial?.font_color || '',
    olc_template_id: partial?.olc_template_id ?? null,
    olc_template_name: partial?.olc_template_name || null,
  }
}

type OlcTemplate = {
  id: string | number
  title?: string
  name?: string
}

function ProductSelectionSummary({
  product,
  knownCostPerPiece,
}: {
  product: OlcProduct | undefined
  knownCostPerPiece?: number | null
}) {
  if (!product) return null
  const info = describeOlcProduct(product)
  return (
    <Alert severity="info" sx={{ mt: 1, mb: 1 }}>
      <Typography variant="body2" sx={{ mb: 0.5 }}>
        <strong>{info.tierLabel}</strong> tier
        {info.deliverySpeed ? ` · ${info.deliverySpeed}` : ''}
      </Typography>
      <Typography variant="body2">{info.postageNote}</Typography>
      {knownCostPerPiece != null && (
        <Typography variant="body2" sx={{ mt: 1 }}>
          Your last sent batch averaged <strong>${knownCostPerPiece.toFixed(2)}/piece</strong> on
          this account (actual OLC charge).
        </Typography>
      )}
      {knownCostPerPiece == null && (
        <Typography variant="body2" sx={{ mt: 1 }} color="text.secondary">
          OLC does not expose per-product prices before you send. After your first batch, actual
          cost per piece will appear here and on the Queue tab.
        </Typography>
      )}
    </Alert>
  )
}

export const OpenLetterSetupPanel: React.FC = () => {
  const queryClient = useQueryClient()
  const [apiTokenInput, setApiTokenInput] = useState('')
  const [batchMinimum, setBatchMinimum] = useState(50)
  const [allowBelow, setAllowBelow] = useState(false)
  const [productId, setProductId] = useState<number | ''>('')
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [templateName, setTemplateName] = useState('')
  const [returnAddress, setReturnAddress] = useState(EMPTY_RETURN_ADDRESS)
  const [presets, setPresets] = useState<MailCreativePreset[]>([])
  const [activePresetId, setActivePresetId] = useState<string>('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  const {
    data: config,
    isLoading: configLoading,
    isError: configError,
    error: configErrorDetail,
    refetch: refetchConfig,
  } = useQuery({
    queryKey: ['open-letter-config'],
    queryFn: () => openLetterService.getConfig(),
  })

  const configured = config?.configured === true
  const usesEnvToken = config?.uses_env_token === true
  const needsUserToken = !configured

  const {
    data: productsData,
    isLoading: productsLoading,
    isError: productsError,
    refetch: refetchProducts,
  } = useQuery({
    queryKey: ['open-letter-products'],
    queryFn: () => openLetterService.listProducts(),
    enabled: configured,
    retry: 1,
  })

  const {
    data: templatesData,
    isLoading: templatesLoading,
    isError: templatesError,
    refetch: refetchTemplates,
    isFetching: templatesFetching,
  } = useQuery({
    queryKey: ['open-letter-templates'],
    queryFn: () => openLetterService.listTemplates(),
    enabled: configured,
    retry: 1,
    staleTime: 0,
    refetchOnMount: 'always',
  })

  const { data: liveTemplateStyle } = useQuery({
    queryKey: ['open-letter-template-style', templateId],
    queryFn: () => openLetterService.getTemplateStyle(Number(templateId)),
    enabled: configured && templateId !== '',
    retry: 1,
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!liveTemplateStyle?.font_name || !activePresetId) return
    setPresets((prev) =>
      prev.map((p) =>
        (p.id === activePresetId
          ? {
              ...p,
              font_name: liveTemplateStyle.font_name || p.font_name,
              font_color: liveTemplateStyle.font_color || p.font_color,
              olc_template_id: Number(templateId) || p.olc_template_id,
              olc_template_name: templateName || p.olc_template_name,
            }
          : p),
      ),
    )
  }, [liveTemplateStyle, activePresetId, templateId, templateName])

  const setupConfig = React.useMemo(() => {
    if (!config) return config
    if (liveTemplateStyle?.font_name) {
      return { ...config, template_style: liveTemplateStyle }
    }
    return config
  }, [config, liveTemplateStyle])
  const setupSteps = getDirectMailSetupSteps(setupConfig)
  const readyToSend = isDirectMailReadyToSend(setupConfig)

  useEffect(() => {
    if (!config) return
    setBatchMinimum(config.batch_minimum ?? 50)
    setAllowBelow(config.allow_send_below_minimum ?? false)
    if (config.default_product_id != null) setProductId(config.default_product_id)
    if (config.default_template_id != null) setTemplateId(config.default_template_id)
    if (config.default_template_name) setTemplateName(config.default_template_name)
    if (config.return_address && typeof config.return_address === 'object') {
      const ra = config.return_address as Record<string, string>
      setReturnAddress({
        address1: ra.address1 || '',
        address2: ra.address2 || '',
        city: ra.city || '',
        state: ra.state || '',
        zip: ra.zip || '',
      })
    }
    const loaded = (config.creative_presets || []).map((p) => newPreset(p))
    setPresets(loaded)
    setActivePresetId(config.active_creative_preset_id || loaded[0]?.id || '')
  }, [config])

  const activePreset = presets.find((p) => p.id === activePresetId) || presets[0]

  const updateActivePreset = (patch: Partial<MailCreativePreset>) => {
    if (!activePreset) return
    setPresets((prev) =>
      prev.map((p) => (p.id === activePreset.id ? { ...p, ...patch } : p)),
    )
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      openLetterService.saveConfig({
        ...(apiTokenInput ? { api_token: apiTokenInput } : {}),
        use_demo_api: config?.use_demo_api ?? false,
        batch_minimum: batchMinimum,
        allow_send_below_minimum: allowBelow,
        default_product_id: productId === '' ? null : productId,
        default_template_id: templateId === '' ? null : templateId,
        default_template_name: templateName || null,
        return_address:
          returnAddress.address1.trim()
          && returnAddress.city.trim()
          && returnAddress.state.trim()
          && returnAddress.zip.trim()
            ? returnAddress
            : null,
        creative_presets: presets.map((p) => ({
          ...p,
          phone: p.phone ? formatPhoneNumber(p.phone) : p.phone,
        })),
        active_creative_preset_id: activePresetId || presets[0]?.id || null,
      }),
    onSuccess: () => {
      setApiTokenInput('')
      setSaveMessage('Mail settings saved.')
      queryClient.invalidateQueries({ queryKey: ['open-letter-config'] })
      queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
    },
    onError: (e: Error) => setSaveMessage(e.message),
  })

  const products = sortOlcProducts(extractOlcListRows(productsData) as OlcProduct[])
  const templates = extractOlcListRows(templatesData) as OlcTemplate[]
  const selectedProduct = productId !== '' ? products.find((p) => Number(p.id) === productId) : undefined
  const envelopeOptions = listOlcEnvelopeTypes(products, selectedProduct?.productType)
  const canSaveMailSettings = configured && productId !== '' && templateId !== ''

  const handleProductChange = (nextId: number | '') => {
    setProductId(nextId)
    if (nextId === '' || !activePreset) return
    const product = products.find((p) => Number(p.id) === nextId)
    if (product?.envelopeType) {
      updateActivePreset({ envelope_color: product.envelopeType })
    }
  }
  if (configLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (configError) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={() => refetchConfig()}>
            Retry
          </Button>
        }
      >
        Could not load Open Letter settings:{' '}
        {(configErrorDetail as Error)?.message || 'Unknown error'}
      </Alert>
    )
  }

  return (
    <Box sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Paper sx={{ p: { xs: 1.5, sm: 2 }, mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
          <Typography variant="subtitle1">Setup checklist</Typography>
          {readyToSend ? (
            <Chip label="Ready to send" color="success" size="small" />
          ) : (
            <Chip label="Finish setup to send mail" color="warning" size="small" />
          )}
        </Box>
        <List dense disablePadding>
          {setupSteps.map((step) => (
            <ListItem key={step.id} disableGutters sx={{ py: 0.25 }}>
              <ListItemIcon sx={{ minWidth: 32 }}>
                {step.done ? (
                  <CheckCircleIcon color="success" fontSize="small" />
                ) : (
                  <RadioButtonUncheckedIcon color="disabled" fontSize="small" />
                )}
              </ListItemIcon>
              <ListItemText
                primary={step.label}
                secondary={!step.required ? 'Recommended' : undefined}
                primaryTypographyProps={{ variant: 'body2' }}
              />
            </ListItem>
          ))}
        </List>
      </Paper>

      {needsUserToken && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            Connect Open Letter
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Paste your API key from{' '}
            <a href={OLC_TEMPLATE_URL} target="_blank" rel="noopener noreferrer">
              Open Letter Connect
            </a>
            {' '}to continue.
          </Typography>
          <TextField
            fullWidth
            label="Open Letter API token"
            type="password"
            value={apiTokenInput}
            onChange={(e) => setApiTokenInput(e.target.value)}
            margin="normal"
            size="small"
          />
          <Button
            variant="contained"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !apiTokenInput}
            sx={{ mt: 1 }}
          >
            Save API key
          </Button>
        </Paper>
      )}

      {configured && usesEnvToken && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Open Letter is connected for your account. Choose your mail defaults below, then click
          <strong> Save mail settings</strong>.
        </Alert>
      )}

      {configured && (
        <>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Mail piece defaults
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Required before you can send a batch. Envelope color is mostly cosmetic — compare
              delivery speed and postage type (Live vs Forever) below.
            </Typography>

            <Accordion sx={{ mb: 2 }} disableGutters>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="body2" fontWeight={600}>
                  Live vs Forever — which should I pick?
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  <strong>Forever is not the cheaper option.</strong> It is a premium “real stamp”
                  look used on Real Penned letters. <strong>Live</strong> is standard metered postage
                  and is what most professional letter campaigns use. Pick Forever when the
                  handwritten aesthetic is worth the extra cost; pick Live for routine outreach at
                  scale.
                </Typography>
                <TableContainer sx={{ overflowX: 'auto' }}>
                  <Table size="small" sx={{ minWidth: 480 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Postage</TableCell>
                        <TableCell>What it is</TableCell>
                        <TableCell>Typical cost</TableCell>
                        <TableCell>Best for</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {POSTAGE_COMPARISON.map((row) => (
                        <TableRow key={row.postage}>
                          <TableCell>{row.postage}</TableCell>
                          <TableCell>{row.summary}</TableCell>
                          <TableCell>{row.cost}</TableCell>
                          <TableCell>{row.bestFor}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
                <Button
                  href={OLC_PRICING_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  endIcon={<OpenInNewIcon />}
                  size="small"
                  sx={{ mt: 2 }}
                >
                  Open Letter published pricing (contact for exact rates)
                </Button>
              </AccordionDetails>
            </Accordion>

            {(productsLoading || templatesLoading) && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <CircularProgress size={20} />
                <Typography variant="body2" color="text.secondary">
                  Loading products and templates from Open Letter…
                </Typography>
              </Box>
            )}

            {productsError && (
              <Alert
                severity="error"
                sx={{ mb: 2 }}
                action={
                  <Button color="inherit" size="small" onClick={() => refetchProducts()}>
                    Retry
                  </Button>
                }
              >
                Failed to load products from Open Letter.
              </Alert>
            )}

            {templatesError && (
              <Alert
                severity="error"
                sx={{ mb: 2 }}
                action={
                  <Button color="inherit" size="small" onClick={() => refetchTemplates()}>
                    Retry
                  </Button>
                }
              >
                Failed to load templates from Open Letter.
              </Alert>
            )}

            <TextField
              select
              fullWidth
              label="Product (envelope / postage)"
              value={productId}
              onChange={(e) => handleProductChange(e.target.value === '' ? '' : Number(e.target.value))}
              margin="normal"
              size="small"
              required
              disabled={productsLoading || products.length === 0}
              helperText={
                products.length === 0 && !productsLoading
                  ? 'No products returned — try Retry or restart the backend dev server.'
                  : undefined
              }
            >
              <MenuItem value="">— Select —</MenuItem>
              {products.map((p) => {
                const tier = describeOlcProduct(p).tierLabel
                return (
                  <MenuItem key={String(p.id)} value={Number(p.id)}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                      <Typography variant="body2" sx={{ flex: 1 }}>
                        {formatOlcProductLabel(p)}
                      </Typography>
                      <Chip label={tier} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.65rem' }} />
                    </Box>
                  </MenuItem>
                )
              })}
            </TextField>

            <ProductSelectionSummary
              product={selectedProduct}
              knownCostPerPiece={config?.estimated_cost_per_piece}
            />

            <TextField
              select
              fullWidth
              label="Template"
              value={templateId}
              onChange={(e) => {
                const id = e.target.value === '' ? '' : Number(e.target.value)
                setTemplateId(id)
                const t = templates.find((x) => Number(x.id) === id)
                setTemplateName(t?.title || t?.name || '')
              }}
              margin="normal"
              size="small"
              required
              disabled={templatesLoading || templates.length === 0}
              helperText={
                templates.length === 0 && !templatesLoading
                  ? 'No templates found — create one in Open Letter Connect, then Retry.'
                  : undefined
              }
            >
              <MenuItem value="">— Select —</MenuItem>
              {templates.map((t) => {
                const tpl = t as OlcTemplate & { product?: { name?: string; productType?: string } }
                const productHint = tpl.product?.name || tpl.product?.productType
                const label = tpl.title || tpl.name || tpl.id
                return (
                  <MenuItem key={String(t.id)} value={Number(t.id)}>
                    {label}
                    {productHint ? ` · ${productHint}` : ''}
                  </MenuItem>
                )
              })}
            </TextField>

            <Box
              sx={{
                display: 'flex',
                flexDirection: { xs: 'column', sm: 'row' },
                flexWrap: 'wrap',
                gap: 1,
                mt: 1,
                width: '100%',
              }}
            >
              <Button
                href={OLC_TEMPLATE_URL}
                target="_blank"
                rel="noopener noreferrer"
                endIcon={<OpenInNewIcon />}
                sx={{ width: { xs: '100%', sm: 'auto' } }}
              >
                Create or edit templates in Open Letter Connect
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={() => refetchTemplates()}
                disabled={templatesFetching}
                sx={{ width: { xs: '100%', sm: 'auto' } }}
              >
                {templatesFetching ? 'Refreshing…' : 'Refresh templates'}
              </Button>
            </Box>
            {templates.length === 0 && !templatesLoading && (
              <Alert severity="info" sx={{ mt: 2 }}>
                No templates loaded. If you just created &quot;Standard&quot; in Open Letter Connect,
                click <strong>Refresh templates</strong>.
              </Alert>
            )}
          </Paper>

          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Creative presets
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Track sender name (e.g. Ben vs Bessy), envelope/font, and whether email/website
              appear on the letter. Keep your Open Letter Connect template aligned with the
              declared envelope/font. Scan and response rates compare by these fields over time.
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
              <TextField
                select
                size="small"
                label="Active preset"
                value={activePreset?.id || ''}
                onChange={(e) => setActivePresetId(e.target.value)}
                sx={{ minWidth: 220 }}
              >
                {presets.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.label || p.sender_display_name || p.id}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                size="small"
                variant="outlined"
                onClick={() => {
                  const created = newPreset({ label: `Creative ${presets.length + 1}` })
                  setPresets((prev) => [...prev, created])
                  setActivePresetId(created.id)
                }}
              >
                Add preset
              </Button>
              {activePreset && presets.length > 1 && (
                <Button
                  size="small"
                  color="warning"
                  onClick={() => {
                    const next = presets.filter((p) => p.id !== activePreset.id)
                    setPresets(next)
                    setActivePresetId(next[0]?.id || '')
                  }}
                >
                  Delete active
                </Button>
              )}
            </Box>
            {activePreset ? (
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  <TextField
                    fullWidth
                    label="Preset label"
                    size="small"
                    value={activePreset.label || ''}
                    onChange={(e) => updateActivePreset({ label: e.target.value })}
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    label="Sender first name"
                    size="small"
                    value={activePreset.first_name || ''}
                    onChange={(e) => {
                      const first_name = e.target.value
                      updateActivePreset({
                        first_name,
                        label: [
                          first_name.trim(),
                          (activePreset.last_name || '').trim(),
                        ].filter(Boolean).join(' ') || activePreset.label,
                      })
                    }}
                    required
                  />
                </Grid>
                <Grid item xs={12} sm={3}>
                  <TextField
                    fullWidth
                    label="Sender last name"
                    size="small"
                    value={activePreset.last_name || ''}
                    onChange={(e) => {
                      const last_name = e.target.value
                      updateActivePreset({
                        last_name,
                        label: [
                          (activePreset.first_name || '').trim(),
                          last_name.trim(),
                        ].filter(Boolean).join(' ') || activePreset.label,
                      })
                    }}
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    fullWidth
                    label="Sender phone (Please call…)"
                    size="small"
                    value={activePreset.phone || ''}
                    onChange={(e) => updateActivePreset({ phone: e.target.value })}
                    onBlur={(e) => {
                      const formatted = formatPhoneNumber(e.target.value.trim())
                      if (formatted !== (activePreset.phone || '')) {
                        updateActivePreset({ phone: formatted })
                      }
                    }}
                    placeholder="(312) 555-0100"
                    helperText="Saved as (XXX) XXX-XXXX"
                    required
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    fullWidth
                    label="Sender email"
                    size="small"
                    value={activePreset.email || ''}
                    onChange={(e) => {
                      const email = e.target.value
                      updateActivePreset({
                        email,
                        ...(email.trim() ? { include_email: true } : {}),
                      })
                    }}
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    fullWidth
                    label="Website"
                    size="small"
                    value={activePreset.website || ''}
                    onChange={(e) => {
                      const website = e.target.value
                      updateActivePreset({
                        website,
                        ...(website.trim() ? { include_website: true } : {}),
                      })
                    }}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={(
                      <Checkbox
                        checked={Boolean(activePreset.include_email)}
                        onChange={(e) => updateActivePreset({ include_email: e.target.checked })}
                      />
                    )}
                    label="Include email on mailer"
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <FormControlLabel
                    control={(
                      <Checkbox
                        checked={Boolean(activePreset.include_website)}
                        onChange={(e) => updateActivePreset({ include_website: e.target.checked })}
                      />
                    )}
                    label="Include website on mailer"
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    select
                    fullWidth
                    label="Envelope (OLC)"
                    size="small"
                    value={activePreset.envelope_color || ''}
                    onChange={(e) => {
                      const envelope = e.target.value
                      updateActivePreset({ envelope_color: envelope })
                      const match = findOlcProductForEnvelope(products, productId, envelope)
                      if (match) {
                        const nextId = Number(match.id)
                        setProductId(nextId)
                        // Keep product/template selection consistent with envelope SKU.
                      }
                    }}
                    helperText={
                      envelopeOptions.length
                        ? 'From your selected Open Letter product type'
                        : 'Load products / pick a product first'
                    }
                  >
                    <MenuItem value="">
                      <em>Select envelope</em>
                    </MenuItem>
                    {envelopeOptions.map((envelope) => (
                      <MenuItem key={envelope} value={envelope}>
                        {envelope}
                      </MenuItem>
                    ))}
                    {activePreset.envelope_color
                      && !envelopeOptions.includes(activePreset.envelope_color) && (
                      <MenuItem value={activePreset.envelope_color}>
                        {activePreset.envelope_color} (saved)
                      </MenuItem>
                    )}
                  </TextField>
                </Grid>
                <Grid item xs={12} sm={8}>
                  {(() => {
                    const font = config?.template_style?.font_name
                      || activePreset.font_name
                      || liveTemplateStyle?.font_name
                    const ink = config?.template_style?.font_color
                      || activePreset.font_color
                      || liveTemplateStyle?.font_color
                    if (font) {
                      return (
                        <Alert severity="success" sx={{ py: 0.5 }}>
                          Confirmed from template:{' '}
                          <strong>{font}</strong>
                          {ink ? <> · ink <strong>{ink}</strong></> : null}
                          . Change font/ink in Open Letter Connect, then refresh templates / save.
                        </Alert>
                      )
                    }
                    return (
                      <Alert severity="warning" sx={{ py: 0.5 }}>
                        Select a letter template above to auto-confirm font and ink from Connect.
                      </Alert>
                    )
                  })()}
                </Grid>
              </Grid>
            ) : (
              <Alert severity="info">Add a creative preset with sender name and phone before sending.</Alert>
            )}
          </Paper>

          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Return address
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Name on the envelope comes from the active creative’s sender first/last name
              (same fields as above — edit either place). Street below is the return street.
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Return first name"
                  size="small"
                  value={activePreset?.first_name || ''}
                  onChange={(e) => {
                    const first_name = e.target.value
                    updateActivePreset({
                      first_name,
                      label: [
                        first_name.trim(),
                        (activePreset?.last_name || '').trim(),
                      ].filter(Boolean).join(' ') || activePreset?.label,
                    })
                  }}
                  disabled={!activePreset}
                  required
                />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Return last name"
                  size="small"
                  value={activePreset?.last_name || ''}
                  onChange={(e) => {
                    const last_name = e.target.value
                    updateActivePreset({
                      last_name,
                      label: [
                        (activePreset?.first_name || '').trim(),
                        last_name.trim(),
                      ].filter(Boolean).join(' ') || activePreset?.label,
                    })
                  }}
                  disabled={!activePreset}
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  fullWidth
                  label="Street address"
                  size="small"
                  value={returnAddress.address1}
                  onChange={(e) => setReturnAddress((prev) => ({ ...prev, address1: e.target.value }))}
                />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="City"
                  size="small"
                  value={returnAddress.city}
                  onChange={(e) => setReturnAddress((prev) => ({ ...prev, city: e.target.value }))}
                />
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField
                  fullWidth
                  label="State"
                  size="small"
                  value={returnAddress.state}
                  onChange={(e) => setReturnAddress((prev) => ({ ...prev, state: e.target.value }))}
                />
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField
                  fullWidth
                  label="ZIP"
                  size="small"
                  value={returnAddress.zip}
                  onChange={(e) => setReturnAddress((prev) => ({ ...prev, zip: e.target.value }))}
                />
              </Grid>
            </Grid>
          </Paper>

          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              Batch settings
            </Typography>
            <TextField
              fullWidth
              type="number"
              label="Batch minimum (pieces before Send unlocks)"
              value={batchMinimum}
              onChange={(e) => setBatchMinimum(Math.max(1, Number(e.target.value) || 1))}
              margin="normal"
              size="small"
              inputProps={{ min: 1 }}
              helperText="Lower this for local testing (e.g. 1–5 pieces)."
            />
            <Button
              variant="text"
              size="small"
              onClick={() => setAllowBelow((prev) => !prev)}
              sx={{ mt: 1 }}
            >
              {allowBelow ? 'Disable' : 'Enable'} send below minimum (testing only)
            </Button>
          </Paper>

          <Button
            variant="contained"
            size="large"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !canSaveMailSettings}
            sx={{ width: { xs: '100%', sm: 'auto' } }}
          >
            Save mail settings
          </Button>
          {!canSaveMailSettings && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Select a product and template above to enable save.
            </Typography>
          )}
          {saveMessage && (
            <Alert severity={saveMutation.isError ? 'error' : 'success'} sx={{ mt: 2 }}>
              {saveMessage}
            </Alert>
          )}
        </>
      )}
    </Box>
  )
}
