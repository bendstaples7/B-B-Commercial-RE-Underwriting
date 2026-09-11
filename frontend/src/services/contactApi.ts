/**
 * Contact / PropertyContact API — create, link, unlink, clear owner person.
 */
import api from '@/services/httpClient'
import type {
  Contact,
  PropertyContact,
  ContactCreatePayload,
  ContactUpdatePayload,
  PropertyContactLinkRequest,
} from '@/types'

export const contactService = {
  /** POST /api/contacts/ — create a new contact */
  createContact: async (data: ContactCreatePayload): Promise<Contact> => {
    const response = await api.post<Contact>('/contacts/', data)
    return response.data
  },

  /** GET /api/contacts/search — find contacts by name for linking */
  searchContacts: async (params: {
    q: string
    limit?: number
    excludePropertyId?: number
  }): Promise<Contact[]> => {
    const response = await api.get<{ results: Contact[] }>('/contacts/search', {
      params: {
        q: params.q,
        limit: params.limit ?? 20,
        exclude_property_id: params.excludePropertyId,
      },
    })
    return response.data.results ?? []
  },

  /** GET /api/contacts/{id} — get a contact with phones, emails, and linked properties */
  getContact: async (id: number): Promise<Contact> => {
    const response = await api.get<Contact>(`/contacts/${id}`)
    return response.data
  },

  /** PUT /api/contacts/{id} — update a contact */
  updateContact: async (id: number, data: ContactUpdatePayload): Promise<Contact> => {
    const response = await api.put<Contact>(`/contacts/${id}`, data)
    return response.data
  },

  /** DELETE /api/contacts/{id} — delete a contact (cascades to phones, emails, property links) */
  deleteContact: async (id: number): Promise<void> => {
    await api.delete(`/contacts/${id}`)
  },

  /** GET /api/properties/{propertyId}/contacts — list contacts; pass includeFormerOwners for Log Call dial targets. */
  getPropertyContacts: async (
    propertyId: number,
    options?: { includeFormerOwners?: boolean },
  ): Promise<PropertyContact[]> => {
    const params = options?.includeFormerOwners ? { include_former_owners: '1' } : undefined
    const response = await api.get<PropertyContact[]>(`/properties/${propertyId}/contacts`, { params })
    return response.data
  },

  /** POST /api/properties/{propertyId}/contacts — link a contact to a property */
  linkContactToProperty: async (
    propertyId: number,
    data: PropertyContactLinkRequest
  ): Promise<PropertyContact> => {
    const response = await api.post<PropertyContact>(`/properties/${propertyId}/contacts`, data)
    return response.data
  },

  /** DELETE /api/properties/{propertyId}/contacts/{contactId} — unlink a contact from a property */
  unlinkContactFromProperty: async (propertyId: number, contactId: number): Promise<void> => {
    await api.delete(`/properties/${propertyId}/contacts/${contactId}`)
  },

  /**
   * POST /api/properties/{propertyId}/clear-owner-person
   * Clear flat owner name slots (and optionally unlink a matching contact).
   */
  clearOwnerPerson: async (
    propertyId: number,
    data: {
      first_name?: string | null
      last_name?: string | null
      contact_id?: number | null
      reason?: string | null
    },
  ): Promise<{
    cleared_slots: string[]
    unlinked_contact_id: number | null
    display_name: string
  }> => {
    const response = await api.post<{
      cleared_slots: string[]
      unlinked_contact_id: number | null
      display_name: string
    }>(`/properties/${propertyId}/clear-owner-person`, data)
    return response.data
  },
}
