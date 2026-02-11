/**
 * Test utilities and custom render functions
 */
import { ReactElement } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material/styles'

const theme = createTheme()

interface AllTheProvidersProps {
  children: React.ReactNode
}

const AllTheProviders = ({ children }: AllTheProvidersProps) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>{children}</ThemeProvider>
    </QueryClientProvider>
  )
}

const customRender = (
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) => render(ui, { wrapper: AllTheProviders, ...options })

export * from '@testing-library/react'
export { customRender as render }

/**
 * Create a mock query client for testing
 */
export const createTestQueryClient = () => {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

/**
 * Wait for async operations to complete
 */
export const waitForAsync = () => new Promise(resolve => setTimeout(resolve, 0))

/**
 * Mock API response helper
 */
export const mockApiResponse = <T,>(data: T, delay: number = 0): Promise<T> => {
  return new Promise((resolve) => {
    setTimeout(() => resolve(data), delay)
  })
}

/**
 * Mock API error helper
 */
export const mockApiError = (message: string, delay: number = 0): Promise<never> => {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(message)), delay)
  })
}
