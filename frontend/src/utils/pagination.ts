/**
 * Computes the total number of pages for a paginated result set.
 * @param total - Total number of records
 * @param perPage - Number of records per page
 * @returns Total pages, or 0 if total is 0
 */
export function computeTotalPages(total: number, perPage: number): number {
  return total > 0 ? Math.ceil(total / perPage) : 0
}

/**
 * Clamps a requested page number to the valid range [1, totalPages].
 * @param page - The requested page number
 * @param totalPages - The total number of pages
 * @returns A page number guaranteed to be in [1, totalPages]
 */
export function clampPage(page: number, totalPages: number): number {
  return Math.min(Math.max(1, page), Math.max(1, totalPages))
}
