import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { liveUiCapturePlugin } from '../scripts/live-ui/vite-plugin.mjs'

export default defineConfig(({ command, mode }) => {
  const rootDir = path.resolve(__dirname, '..')
  // Vite's envDir is the project root (shared with backend). Also merge
  // frontend/.env so VITE_* keys that only live there still reach import.meta.env.
  const merged = {
    ...loadEnv(mode, rootDir, ''),
    ...loadEnv(mode, __dirname, ''),
  }
  for (const [key, value] of Object.entries(merged)) {
    if (key.startsWith('VITE_') && !process.env[key]) {
      process.env[key] = value
    }
  }

  const isPackingHarness = process.env.CC_PACKING_HARNESS === '1'

  return {
    envDir: rootDir,
    plugins: [
      react(),
      // Packing-geometry harness starts its own Vite server; skip live-ui middleware
      // so HMR/capture hooks cannot keep networkidle from settling in CI.
      ...(command === 'serve' && !isPackingHarness
        ? [liveUiCapturePlugin()]
        : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    ...(isPackingHarness
      ? {
          optimizeDeps: {
            include: [
              'react',
              'react-dom',
              'react-dom/client',
              'react/jsx-runtime',
              'react/jsx-dev-runtime',
              '@emotion/react',
              '@emotion/styled',
              '@mui/material',
              '@mui/material/styles',
              '@mui/system',
              '@mui/icons-material/ArrowBack',
            ],
          },
        }
      : {}),
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            // Do NOT put react/react-dom/scheduler/react-router in a separate
            // chunk against a catch-all vendor: that produces
            // "Cannot read properties of undefined (reading 'createContext')"
            // when vendor evaluates before the React binding is initialized.
            // Put React into vendor with other deps; only split large isolates.
            if (!id.includes('node_modules')) {
              // Keep shared HTTP/API + snackbar out of the entry chunk so lazy
              // routes (UnifiedLeadCommandCenter) never `import` from `index-*.js`
              // (circular entry↔lazy graph that blanks /leads/:id in prod).
              // Incomplete by nature — scripts/assert_frontend_dist_assets.py is
              // the hard regression gate for any leftover lazy→index import.
              const norm = id.replace(/\\/g, '/')
              if (
                norm.includes('/services/httpClient')
                || norm.includes('/services/api.ts')
                || norm.includes('/services/api.js')
                || norm.includes('/services/leadApi')
                || norm.includes('/services/entityResolutionApi')
                || norm.includes('/services/openLetterApi')
                || norm.includes('/services/schemas')
                // Runtime enums/constants from @/types must not live in the entry
                // chunk (lazy routes import them → lazy↔entry cycle).
                || norm.includes('/src/types/')
                || norm.endsWith('/src/types/index.ts')
                || norm.endsWith('/src/types/index.js')
                || norm.endsWith('/src/types.ts')
              ) {
                return 'api'
              }
              // Contexts, snackbar, and shared display utils outside entry.
              if (
                norm.includes('/context/')
                || norm.includes('/components/AppSnackbar')
                || norm.includes('/utils/searchResultDisplay')
              ) {
                return 'ui-shared'
              }
              return
            }
            if (
              id.includes('node_modules/react-dom')
              || id.includes('node_modules/react/')
              || id.includes('node_modules/react-router')
              || id.includes('node_modules/scheduler')
            ) {
              return 'vendor'
            }
            if (id.includes('@mui')) return 'mui'
            if (id.includes('ag-grid')) return 'ag-grid'
            if (id.includes('recharts')) return 'recharts'
            if (id.includes('@react-google-maps') || id.includes('google-maps')) return 'maps'
            if (id.includes('@dnd-kit')) return 'dnd'
            return 'vendor'
          },
        },
      },
    },
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://localhost:5000',
          changeOrigin: true,
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
