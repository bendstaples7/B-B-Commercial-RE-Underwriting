import { describe, expect, it } from 'vitest'
import {
  getActiveCreativePreset,
  getDirectMailSetupSteps,
  getOlcCatalogSendLines,
  isDirectMailReadyToSend,
  isSenderCreativeReady,
  isTemplateStyleConfirmed,
} from '@/utils/directMailSetup'
import type { OpenLetterConfig } from '@/services/openLetterApi'
import type { OlcProduct } from '@/utils/olcProductHelpers'

function baseConfig(overrides: Partial<OpenLetterConfig> = {}): OpenLetterConfig {
  return {
    configured: true,
    default_product_id: 27,
    default_template_id: 371,
    default_template_name: 'Standard',
    return_address: {
      address1: '1343 W Irving',
      city: 'Chicago',
      state: 'IL',
      zip: '60613',
    },
    creative_presets: [
      {
        id: 'p1',
        label: 'Bessy Tam',
        first_name: 'Bessy',
        last_name: 'Tam',
        phone: '312-555-0100',
        font_name: 'Waiting for the Sunrise',
        font_color: '#25408F',
        envelope_color: 'A6 Blue Mosaic',
        olc_template_id: 371,
        olc_template_name: 'Standard',
      },
    ],
    active_creative_preset_id: 'p1',
    template_style: {
      font_name: 'Waiting for the Sunrise',
      font_color: '#25408F',
      confirmed_from: 'olc_template',
    },
    ...overrides,
  }
}

const personalProduct: OlcProduct = {
  id: 27,
  name: 'Personal Letters, Standard Class',
  productType: 'Personal Letters',
  deliveryType: 'Standard Class',
  postageType: 'Live',
  envelopeType: 'A6 Blue Mosaic',
}

describe('directMailSetup creative readiness', () => {
  it('requires creative sender name and phone (font comes from template)', () => {
    expect(isSenderCreativeReady(baseConfig())).toBe(true)
    expect(isSenderCreativeReady(baseConfig({
      creative_presets: [{ id: 'x', label: 'x', first_name: 'Ben' }],
    }))).toBe(false)
    expect(isTemplateStyleConfirmed(baseConfig())).toBe(true)
    expect(isTemplateStyleConfirmed(baseConfig({
      template_style: null,
      creative_presets: [{ id: 'x', label: 'x', first_name: 'Ben', phone: '1' }],
    }))).toBe(false)
    expect(isDirectMailReadyToSend(baseConfig())).toBe(true)
  })

  it('lists template style confirmation as a required step without leading fontFamily', () => {
    const steps = getDirectMailSetupSteps(baseConfig({
      template_style: null,
      creative_presets: [{ id: 'x', label: 'x', first_name: 'Ben', phone: '1' }],
    }))
    expect(steps.find((s) => s.id === 'template_style')?.required).toBe(true)
    expect(steps.find((s) => s.id === 'template_style')?.done).toBe(false)
    expect(steps.find((s) => s.id === 'creative')?.required).toBe(true)

    const confirmed = getDirectMailSetupSteps(baseConfig())
      .find((s) => s.id === 'template_style')
    expect(confirmed?.done).toBe(true)
    expect(confirmed?.label).toContain('Connect template design readable')
    expect(confirmed?.label).toContain('Standard')
    expect(confirmed?.label).not.toContain('Waiting for the Sunrise')
  })

  it('resolves active creative preset', () => {
    const preset = getActiveCreativePreset(baseConfig())
    expect(preset?.first_name).toBe('Bessy')
  })

  it('builds catalog send lines from OLC product + template (not fontFamily)', () => {
    const lines = getOlcCatalogSendLines(baseConfig(), [personalProduct])
    expect(lines.productLine).toBe(
      'Personal Letters · Standard Class · Live · A6 Blue Mosaic',
    )
    expect(lines.templateLine).toBe('Standard (#371)')
    expect(lines.senderLine).toBe('Bessy Tam')
    expect(lines.productLine).not.toContain('Waiting for the Sunrise')
  })
})
