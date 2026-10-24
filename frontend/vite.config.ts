import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { configDefaults, defineConfig } from 'vitest/config'

// The Neon Auth service lives on another domain, so its session cookie would be third-party and Safari blocks
// those. The app talks to it through its own origin at /neon-auth (a proxy here, a rewrite in vercel.json), which
// makes the cookie first-party everywhere.
const NEON_AUTH_TARGET = process.env.NEON_AUTH_TARGET ?? 'https://ep-flat-glade-ao11yi0v.neonauth.c-2.ap-southeast-1.aws.neon.tech'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    proxy: {
      '/neon-auth': {
        target: NEON_AUTH_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/neon-auth/, '/neondb/auth'),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    css: false,
    exclude: [...configDefaults.exclude, 'e2e/**'], // Playwright runs those
    // The first test to open the Insights Studio loads the chart library, which can take several seconds when the whole
    // suite runs in parallel; the default 5 seconds then fails a test that is only slow.
    testTimeout: 20_000,
  },
})
