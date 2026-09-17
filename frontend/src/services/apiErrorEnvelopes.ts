/**
 * Backend labels that wrap the real reason in `message`.
 * Toasts must show `message`, never these labels alone.
 *
 * Keep in sync with apiErrorEnvelopes.json (CI enforces membership).
 */
import envelopes from './apiErrorEnvelopes.json'

export const API_ERROR_ENVELOPES: ReadonlySet<string> = new Set(envelopes)

export function isApiErrorEnvelope(label: string): boolean {
  return API_ERROR_ENVELOPES.has(label)
}
