/** Format note-derived unit mix for Command Center property rows. */

export type NoteUnitMixRow = {
  units: number
  beds: number
  baths?: number
}

export function formatNoteUnitMixLabel(
  unitMix: NoteUnitMixRow[] | null | undefined,
): string | null {
  if (!unitMix?.length) return null
  const parts: string[] = []
  for (const row of unitMix) {
    if (row == null || row.beds == null || row.units == null) continue
    let piece = `${row.units}×${row.beds} bd`
    if (row.baths != null) {
      piece = `${piece} / ${row.baths} ba`
    }
    parts.push(piece)
  }
  if (!parts.length) return null
  return parts.join(' + ')
}

export function formatAssessorBedsBaths(
  bedrooms: number | null | undefined,
  bathrooms: number | null | undefined,
): string | null {
  if (bedrooms == null && bathrooms == null) return null
  return `${bedrooms ?? '?'} bd / ${bathrooms ?? '?'} ba`
}
