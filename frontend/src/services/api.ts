/**
 * API service layer for backend communication
 */
import axios, { AxiosError, AxiosInstance } from 'axios'
import type {
  AnalysisSession,
  StartAnalysisRequest,
  StartAnalysisResponse,
  UpdateStepDataRequest,
  AdvanceStepRequest,
  StepResult,
  ErrorResponse,
  Report,
} from '@/types'

// Create axios instance with default config
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 second timeout
})

// Request interceptor for adding auth tokens (future use)
api.interceptors.request.use(
  (config) => {
    // Add user_id to requests (temporary until OAuth is implemented)
    const userId = localStorage.getItem('user_id') || 'default_user'
    if (config.data) {
      config.data.user_id = userId
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ErrorResponse>) => {
    if (error.response) {
      // Server responded with error status
      const errorData = error.response.data
      console.error('API Error:', errorData)
      
      // Handle specific error codes
      if (error.response.status === 429) {
        throw new Error('Rate limit exceeded. Please try again later.')
      }
      
      throw new Error(errorData?.message || 'An error occurred')
    } else if (error.request) {
      // Request made but no response received
      console.error('Network Error:', error.request)
      throw new Error('Network error. Please check your connection.')
    } else {
      // Something else happened
      console.error('Error:', error.message)
      throw new Error(error.message)
    }
  }
)

export const analysisService = {
  /**
   * Health check endpoint
   */
  healthCheck: async (): Promise<{ status: string }> => {
    const response = await api.get('/health')
    return response.data
  },

  /**
   * Start a new analysis session
   */
  startAnalysis: async (address: string): Promise<StartAnalysisResponse> => {
    const response = await api.post<StartAnalysisResponse>('/analysis/start', {
      address,
    })
    return response.data
  },

  /**
   * Get current session state
   */
  getSession: async (sessionId: string): Promise<AnalysisSession> => {
    const response = await api.get<AnalysisSession>(`/analysis/${sessionId}`)
    return response.data
  },

  /**
   * Advance to the next workflow step
   */
  advanceToStep: async (
    sessionId: string,
    stepNumber: number,
    approvalData?: Record<string, any>
  ): Promise<StepResult> => {
    const response = await api.post<StepResult>(
      `/analysis/${sessionId}/step/${stepNumber}`,
      { approval_data: approvalData }
    )
    return response.data
  },

  /**
   * Update data for a specific workflow step
   */
  updateStepData: async (
    sessionId: string,
    stepNumber: number,
    data: Record<string, any>
  ): Promise<StepResult> => {
    const response = await api.put<StepResult>(
      `/analysis/${sessionId}/step/${stepNumber}`,
      data
    )
    return response.data
  },

  /**
   * Navigate back to a previous workflow step
   */
  goBackToStep: async (
    sessionId: string,
    stepNumber: number
  ): Promise<AnalysisSession> => {
    const response = await api.post<AnalysisSession>(
      `/analysis/${sessionId}/back/${stepNumber}`
    )
    return response.data
  },

  /**
   * Generate analysis report
   */
  generateReport: async (sessionId: string): Promise<Report> => {
    const response = await api.get<{ report: Report }>(
      `/analysis/${sessionId}/report`
    )
    return response.data.report
  },

  /**
   * Export report to Excel
   */
  exportToExcel: async (sessionId: string): Promise<Blob> => {
    const response = await api.get(`/analysis/${sessionId}/export/excel`, {
      responseType: 'blob',
    })
    return response.data
  },

  /**
   * Export report to Google Sheets
   */
  exportToGoogleSheets: async (
    sessionId: string,
    credentials: Record<string, any>
  ): Promise<{ url: string; message: string }> => {
    const response = await api.post<{ url: string; message: string }>(
      `/analysis/${sessionId}/export/sheets`,
      { credentials }
    )
    return response.data
  },
}

// Retry configuration for React Query
export const queryConfig = {
  retry: (failureCount: number, error: Error) => {
    // Don't retry on 4xx errors (client errors)
    if (error.message.includes('Rate limit') || error.message.includes('400')) {
      return false
    }
    // Retry up to 3 times for network errors and 5xx errors
    return failureCount < 3
  },
  retryDelay: (attemptIndex: number) => {
    // Exponential backoff: 1s, 2s, 4s
    return Math.min(1000 * 2 ** attemptIndex, 30000)
  },
  staleTime: 5 * 60 * 1000, // 5 minutes
  cacheTime: 10 * 60 * 1000, // 10 minutes
}

export default api
