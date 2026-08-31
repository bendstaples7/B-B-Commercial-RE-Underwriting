/**
 * Channel ROI API — Direct Mail vs Facebook spend efficiency.
 */
import api from '@/services/api'

export interface ChannelRoiSettings {
  meta_connected: boolean
  meta_ad_account_id: string | null
  has_meta_token: boolean
  expected_profit_per_deal: number | null
  assumed_close_rate: number | null
  last_synced_at: string | null
  last_sync_error: string | null
}

export interface ChannelSummary {
  spend: number
  responses: number
  cost_per_response: number | null
  response_rate: number | null
  denominator: number | null
  denominator_label: string
  projected_roi: number | null
}

export interface ChannelCampaignRow {
  id: number
  name: string
  status?: string | null
  spend: number
  denominator: number | null
  denominator_label: string
  responses: number
  response_rate: number | null
  cost_per_response: number | null
  projected_roi: number | null
  submitted_at?: string | null
  link_clicks?: number
  impressions?: number
  synced_at?: string | null
}

export interface ChannelRoiDashboard {
  settings: ChannelRoiSettings
  projection_knobs_set: boolean
  channels: {
    direct_mail: ChannelSummary
    facebook: ChannelSummary
  }
  direct_mail_campaigns: ChannelCampaignRow[]
  facebook_campaigns: ChannelCampaignRow[]
}

export interface FacebookCampaignOption {
  id: number
  meta_campaign_id: string
  name: string
  status?: string | null
}

export type ChannelRoiSettingsPatch = {
  expected_profit_per_deal?: number
  assumed_close_rate?: number
  meta_ad_account_id?: string
  meta_access_token?: string
  clear_meta_token?: boolean
}

export const channelRoiService = {
  async getDashboard(): Promise<ChannelRoiDashboard> {
    const response = await api.get<ChannelRoiDashboard>('/marketing/channel-roi')
    return response.data
  },

  async patchSettings(body: ChannelRoiSettingsPatch): Promise<ChannelRoiSettings> {
    const response = await api.patch<ChannelRoiSettings>('/marketing/channel-roi/settings', body)
    return response.data
  },

  async syncFacebook(): Promise<{ synced?: number; skipped?: boolean; reason?: string }> {
    const response = await api.post('/marketing/channel-roi/sync')
    return response.data
  },

  async listFacebookCampaigns(): Promise<{ campaigns: FacebookCampaignOption[] }> {
    const response = await api.get<{ campaigns: FacebookCampaignOption[] }>(
      '/marketing/channel-roi/facebook-campaigns',
    )
    return response.data
  },
}

export default channelRoiService
