import { defineConfig, devices } from '@playwright/test'

// End-to-end tests drive a real browser against the app. By default they start the dev server and talk to the
// deployed API. Point them elsewhere with E2E_BASE_URL (for example a Vercel preview URL), and supply a test
// account with E2E_EMAIL and E2E_PASSWORD to run the signed-in journey; without them those tests are skipped.
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : { command: 'npm run dev -- --port 5173 --strictPort', url: 'http://localhost:5173', reuseExistingServer: true, timeout: 60_000 },
})
