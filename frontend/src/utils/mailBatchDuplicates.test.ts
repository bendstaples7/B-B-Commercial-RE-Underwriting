import { analyzeMailBatchDuplicates } from './mailBatchDuplicates'
import type { MailQueueItem } from '@/services/openLetterApi'

describe('mailBatchDuplicates', () => {
  const base = (overrides: Partial<MailQueueItem>): MailQueueItem => ({
    id: 1,
    lead_id: 10,
    user_id: 'u1',
    status: 'queued',
    mailing_address: '100 Main St',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60614',
    mailing_dedupe_key: '100 main|chicago|il|60614',
    ...overrides,
  })

  it('flags extras that share a mailing_dedupe_key', () => {
    const items = [
      base({ id: 2, lead_id: 20 }),
      base({ id: 1, lead_id: 10 }),
      base({
        id: 3,
        lead_id: 30,
        mailing_dedupe_key: '200 other|chicago|il|60614',
        mailing_address: '200 Other',
      }),
    ]
    const info = analyzeMailBatchDuplicates(items)
    expect(info.duplicateGroupCount).toBe(1)
    expect(info.duplicateExtraCount).toBe(1)
    expect(info.keeperItemIds.has(1)).toBe(true)
    expect(info.duplicateItemIds.has(1)).toBe(true)
    expect(info.duplicateItemIds.has(2)).toBe(true)
    expect(info.duplicateItemIds.has(3)).toBe(false)
  })
})
