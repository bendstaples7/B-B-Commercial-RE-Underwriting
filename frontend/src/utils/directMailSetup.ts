import type { OpenLetterConfig } from '@/services/openLetterApi'

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

export function getDirectMailSetupSteps(config: OpenLetterConfig | undefined): DirectMailSetupStep[] {
  const configured = config?.configured === true
  const hasProduct = config?.default_product_id != null
  const hasTemplate = config?.default_template_id != null
  const hasReturnAddress = Boolean(
    config?.return_address
    && typeof config.return_address === 'object'
    && config.return_address.address1
    && config.return_address.city
    && config.return_address.state
    && config.return_address.zip,
  )

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
      id: 'return_address',
      label: 'Set return address on envelopes',
      done: hasReturnAddress,
      required: false,
    },
  ]
}

export function isDirectMailReadyToSend(config: OpenLetterConfig | undefined): boolean {
  return getDirectMailSetupSteps(config)
    .filter((step) => step.required)
    .every((step) => step.done)
}
