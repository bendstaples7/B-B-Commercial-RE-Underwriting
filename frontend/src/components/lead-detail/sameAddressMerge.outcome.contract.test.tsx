/**
 * Forbid navigate-only merge success on Command Center (outcome-blind-success-path).
 * First enforce site: same-address banner + ULCC wiring. Broader CC mutation
 * handlers are out of scope for this gate until they share the helper.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('contract — same-address merge must not be navigate-only', () => {
  const banner = readFileSync(
    resolve(__dirname, './SameAddressMergeBanner.tsx'),
    'utf8',
  )
  const ulcc = readFileSync(
    resolve(__dirname, '../UnifiedLeadCommandCenter.tsx'),
    'utf8',
  )
  const helper = readFileSync(
    resolve(__dirname, '../../utils/afterCommandCenterMutation.ts'),
    'utf8',
  )

  it('requires onMerged and does not navigate after merge without it', () => {
    expect(banner).toMatch(/onMerged:\s*\(payload:\s*SameAddressMergedPayload\)/)
    expect(banner).toContain('await onMerged({')
    expect(banner).toContain('winnerId: result.winner_id')
    // Success path must not call navigate directly (router no-op on same lead).
    expect(banner).not.toMatch(/mergeInto[\s\S]{0,400}navigate\(`\/leads\/\$\{/)
    expect(banner).not.toContain("navigate(`/leads/${result.winner_id}`)")
  })

  it('ULCC wires afterCommandCenterMutation through onMerged', () => {
    expect(ulcc).toContain('afterCommandCenterMutation')
    expect(ulcc).toContain('onMerged={async ({ winnerId, loserId })')
    expect(ulcc).toMatch(/SameAddressMergeBanner[\s\S]*onMerged=/)
  })

  it('shared helper invalidates commandCenter keys', () => {
    expect(helper).toContain('invalidateQueries')
    expect(helper).toContain("['commandCenter'")
    expect(helper).toContain('export async function afterCommandCenterMutation')
  })
})
