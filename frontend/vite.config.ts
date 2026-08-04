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

  return {
    envDir: rootDir,
    plugins: [
      react(),
      ...(command === 'serve' ? [liveUiCapturePlugin()] : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            // Do NOT put react/react-dom/scheduler/react-router in a separate
            // chunk against a catch-all vendor: that produces
            // "Cannot read properties of undefined (reading 'createContext')"
            // when vendor evaluates before the React binding is initialized.
            // Put React into vendor with other deps; only split large isolates.
            if (!id.includes('node_modules')) return
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
