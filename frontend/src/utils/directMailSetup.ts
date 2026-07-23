import type { MailCreativePreset, OpenLetterConfig } from '@/services/openLetterApi'
import { formatOlcProductLabel, type OlcProduct } from '@/utils/olcProductHelpers'

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

/**
 * Catalog-facing lines for Ready to Mail / Setup — what we actually send
 * (productId + templateId), not internal template fontFamily.
 */
export function getOlcCatalogSendLines(
  config: OpenLetterConfig | undefined,
  products: OlcProduct[] = [],
): {
  productLine: string | null
  templateLine: string | null
  senderLine: string | null
} {
  const productId = config?.default_product_id
  const product = products.find((p) => Number(p.id) === Number(productId))
  let productLine: string | null = null
  if (product) {
    productLine = formatOlcProductLabel(product)
  } else if (productId != null) {
    const preset = getActiveCreativePreset(config)
    const envelope = preset?.envelope_color?.trim()
    productLine = envelope
      ? `Product #${productId} · ${envelope}`
      : `Product #${productId}`
  }

  const preset = getActiveCreativePreset(config)
  const templateName = (
    config?.default_template_name
    || preset?.olc_template_name
    || ''
  ).trim()
  const templateId = config?.default_template_id ?? preset?.olc_template_id
  let templateLine: string | null = null
  if (templateName && templateId != null) {
    templateLine = `${templateName} (#${templateId})`
  } else if (templateName) {
    templateLine = templateName
  } else if (templateId != null) {
    templateLine = `Template #${templateId}`
  }

  const sender = (preset?.label || preset?.sender_display_name || '').trim()
  return {
    productLine,
    templateLine,
    senderLine: sender || null,
  }
}

export function getDirectMailSetupSteps(config: OpenLetterConfig | undefined): DirectMailSetupStep[] {
  const configured = config?.configured === true
  const hasProduct = config?.default_product_id != null
  const hasTemplate = config?.default_template_id != null
  const hasReturnAddress = hasStreetReturnAddress(config)
  const hasSender = isSenderCreativeReady(config)
  const styleConfirmed = isTemplateStyleConfirmed(config)
  const templateLabel = (
    config?.default_template_name
    || getActiveCreativePreset(config)?.olc_template_name
    || ''
  ).trim()

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
        ? (
          templateLabel
            ? `Connect template design readable (${templateLabel})`
            : 'Connect template design readable'
        )
        : 'Confirm letter template is readable in Connect',
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
