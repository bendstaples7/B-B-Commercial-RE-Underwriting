import type { MailCreativePreset, OpenLetterConfig } from '@/services/openLetterApi'

export interface DirectMailSetupStep {
  id: string
  label: string
  done: boolean
  required: boolean
}

/** OLC list endpoints may return ``data`` as an array or paginated ``{ rows: [] }``. */
export function extractOlcListRows(payload: { data?: unknown } | undefined): unknown[] {
  const data = payload?.data
  if (Array.isArray(data)) return data
  if (data && typeof data === 'object' && Array.isArray((data as { rows?: unknown[] }).rows)) {
    return (data as { rows: unknown[] }).rows
  }
  return []
}

function hasStreetReturnAddress(config: OpenLetterConfig | undefined): boolean {
  const ra = config?.return_address
  return Boolean(
    ra
    && typeof ra === 'object'
    && ra.address1
    && ra.city
    && ra.state
    && ra.zip,
  )
}

export function getActiveCreativePreset(
  config: OpenLetterConfig | undefined,
): MailCreativePreset | null {
  const presets = config?.creative_presets ?? []
  if (!presets.length) return null
  const activeId = config?.active_creative_preset_id
  if (activeId) {
    const match = presets.find((p) => p.id === activeId)
    if (match) return match
  }
  return presets[0]
}

/** Font/ink come from the OLC template — confirmed when template_style or preset is stamped. */
export function isTemplateStyleConfirmed(config: OpenLetterConfig | undefined): boolean {
  if (config?.template_style?.font_name?.trim()) return true
  const preset = getActiveCreativePreset(config)
  return Boolean(preset?.font_name?.trim())
}

export function isSenderCreativeReady(config: OpenLetterConfig | undefined): boolean {
  const preset = getActiveCreativePreset(config)
  return Boolean(preset?.first_name?.trim() && preset?.phone?.trim())
}

export function getDirectMailSetupSteps(config: OpenLetterConfig | undefined): DirectMailSetupStep[] {
  const configured = config?.configured === true
  const hasProduct = config?.default_product_id != null
  const hasTemplate = config?.default_template_id != null
  const hasReturnAddress = hasStreetReturnAddress(config)
  const hasSender = isSenderCreativeReady(config)
  const styleConfirmed = isTemplateStyleConfirmed(config)

  return [
    {
      id: 'api',
      label: configured ? 'Open Letter account connected' : 'Connect Open Letter API key',
      done: configured,
      required: true,
    },
    {
      id: 'product',
      label: 'Choose envelope / postage product',
      done: hasProduct,
      required: true,
    },
    {
      id: 'template',
      label: 'Choose letter template',
      done: hasTemplate,
      required: true,
    },
    {
      id: 'template_style',
      label: styleConfirmed
        ? `Font/ink confirmed from template (${config?.template_style?.font_name
          || getActiveCreativePreset(config)?.font_name
          || 'set'})`
        : 'Confirm font/ink from Open Letter template',
      done: styleConfirmed,
      required: true,
    },
    {
      id: 'creative',
      label: 'Set creative preset (sender name + phone)',
      done: hasSender,
      required: true,
    },
    {
      id: 'return_address',
      label: 'Set return street address on envelopes',
      done: hasReturnAddress,
      required: true,
    },
  ]
}

export function isDirectMailReadyToSend(config: OpenLetterConfig | undefined): boolean {
  return getDirectMailSetupSteps(config)
    .filter((step) => step.required)
    .every((step) => step.done)
}
