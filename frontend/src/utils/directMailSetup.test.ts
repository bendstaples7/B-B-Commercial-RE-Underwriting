import { describe, expect, it } from 'vitest'
import {
  getActiveCreativePreset,
  getDirectMailSetupSteps,
  isDirectMailReadyToSend,
  isSenderCreativeReady,
  isTemplateStyleConfirmed,
} from '@/utils/directMailSetup'
import type { OpenLetterConfig } from '@/services/openLetterApi'

function baseConfig(overrides: Partial<OpenLetterConfig> = {}): OpenLetterConfig {
  return {
    configured: true,
    default_product_id: 27,
    default_template_id: 371,
    return_address: {
      address1: '1343 W Irving',
      city: 'Chicago',
      state: 'IL',
      zip: '60613',
    },
    creative_presets: [
      {
        id: 'p1',
        label: 'Bessy',
        first_name: 'Bessy',
        last_name: 'Tam',
        phone: '312-555-0100',
        font_name: 'Waiting for the Sunrise',
        font_color: '#25408F',
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

  it('lists template style confirmation as a required step', () => {
    const steps = getDirectMailSetupSteps(baseConfig({
      template_style: null,
      creative_presets: [{ id: 'x', label: 'x', first_name: 'Ben', phone: '1' }],
    }))
    expect(steps.find((s) => s.id === 'template_style')?.required).toBe(true)
    expect(steps.find((s) => s.id === 'template_style')?.done).toBe(false)
    expect(steps.find((s) => s.id === 'creative')?.required).toBe(true)
  })

  it('resolves active creative preset', () => {
    const preset = getActiveCreativePreset(baseConfig())
    expect(preset?.first_name).toBe('Bessy')
  })
})
