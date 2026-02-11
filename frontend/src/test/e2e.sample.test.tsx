/**
 * Sample end-to-end test demonstrating the frontend test environment setup
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from './testUtils'
import {
  mockApiClient,
  mockPropertyFacts,
  mockComparables,
  mockAnalysisSession,
  mockValuationResult,
} from './mockApi'

describe('E2E Test Environment Setup', () => {
  it('should have mock API client available', () => {
    expect(mockApiClient).toBeDefined()
    expect(typeof mockApiClient.startAnalysis).toBe('function')
    expect(typeof mockApiClient.getSession).toBe('function')
  })

  it('should have mock property facts data', () => {
    expect(mockPropertyFacts).toBeDefined()
    expect(mockPropertyFacts.address).toBe('123 Main St, Chicago, IL 60601')
    expect(mockPropertyFacts.units).toBe(4)
    expect(mockPropertyFacts.bedrooms).toBe(8)
  })

  it('should have mock comparables data', () => {
    expect(mockComparables).toBeDefined()
    expect(mockComparables.length).toBe(12)
    expect(mockComparables[0].property_type).toBe('multi_family')
  })

  it('should have mock analysis session', () => {
    expect(mockAnalysisSession).toBeDefined()
    expect(mockAnalysisSession.session_id).toBe('test-session-001')
    expect(mockAnalysisSession.current_step).toBe(1)
  })

  it('should have mock valuation result', () => {
    expect(mockValuationResult).toBeDefined()
    expect(mockValuationResult.comparable_valuations).toHaveLength(5)
    expect(mockValuationResult.arv_range).toBeDefined()
    expect(mockValuationResult.arv_range.conservative).toBe(430000)
    expect(mockValuationResult.arv_range.likely).toBe(460000)
    expect(mockValuationResult.arv_range.aggressive).toBe(490000)
  })

  it('should simulate API delay', async () => {
    const startTime = Date.now()
    const session = await mockApiClient.startAnalysis('123 Main St')
    const endTime = Date.now()

    expect(session).toBeDefined()
    expect(endTime - startTime).toBeGreaterThanOrEqual(100) // Default 100ms delay
  })

  it('should start analysis with custom address', async () => {
    const customAddress = '456 Oak St, Chicago, IL 60602'
    const session = await mockApiClient.startAnalysis(customAddress)

    expect(session.subject_property).toBeDefined()
    expect(session.subject_property?.address).toBe(customAddress)
  })

  it('should get session by ID', async () => {
    const session = await mockApiClient.getSession('test-session-001')

    expect(session).toBeDefined()
    expect(session.session_id).toBe('test-session-001')
  })

  it('should advance workflow step', async () => {
    const result = await mockApiClient.advanceStep('test-session-001', 2)

    expect(result.success).toBe(true)
    expect(result.current_step).toBe(2)
  })

  it('should update step data', async () => {
    const data = { interior_condition: 'high_end' }
    const result = await mockApiClient.updateStepData('test-session-001', 1, data)

    expect(result.success).toBe(true)
    expect(result.data).toEqual(data)
  })

  it('should go back to previous step', async () => {
    const result = await mockApiClient.goBackToStep('test-session-001', 1)

    expect(result.success).toBe(true)
    expect(result.current_step).toBe(1)
  })

  it('should generate report', async () => {
    const report = await mockApiClient.getReport('test-session-001')

    expect(report).toBeDefined()
    expect(report.sections).toBeDefined()
    expect(report.sections.a).toEqual(mockPropertyFacts)
    expect(report.sections.b).toEqual(mockComparables)
  })

  it('should export to Excel', async () => {
    const blob = await mockApiClient.exportToExcel('test-session-001')

    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('application/vnd.ms-excel')
  })

  it('should export to Google Sheets', async () => {
    const result = await mockApiClient.exportToGoogleSheets('test-session-001')

    expect(result).toBeDefined()
    expect(result.url).toContain('docs.google.com/spreadsheets')
  })
})

describe('Test Utilities', () => {
  it('should render with providers', () => {
    const TestComponent = () => <div>Test Component</div>

    render(<TestComponent />)

    expect(screen.getByText('Test Component')).toBeInTheDocument()
  })

  it('should have window.matchMedia mocked', () => {
    const mediaQuery = window.matchMedia('(min-width: 768px)')

    expect(mediaQuery).toBeDefined()
    expect(typeof mediaQuery.matches).toBe('boolean')
  })

  it('should have IntersectionObserver mocked', () => {
    const observer = new IntersectionObserver(() => {})

    expect(observer).toBeDefined()
    expect(typeof observer.observe).toBe('function')
    expect(typeof observer.disconnect).toBe('function')
  })

  it('should have ResizeObserver mocked', () => {
    const observer = new ResizeObserver(() => {})

    expect(observer).toBeDefined()
    expect(typeof observer.observe).toBe('function')
    expect(typeof observer.disconnect).toBe('function')
  })

  it('should have window.scrollTo mocked', () => {
    window.scrollTo(0, 100)

    expect(window.scrollTo).toHaveBeenCalledWith(0, 100)
  })
})
