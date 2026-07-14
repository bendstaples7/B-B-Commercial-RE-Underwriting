import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
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
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
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
