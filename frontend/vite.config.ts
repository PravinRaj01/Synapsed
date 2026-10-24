import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

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
  },
})
