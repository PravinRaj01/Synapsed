import { chromium, type FullConfig } from '@playwright/test'

/**
 * Open every page once before the tests. A freshly started dev server bundles its dependencies the first time a page
 * needs them and then reloads the page, which wipes a half-filled form in whatever test happens to be running.
 * Doing that reload up front keeps the tests about the app. Against a deployed site there is nothing to warm.
 */
export default async function warmUp(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL
  if (!baseURL || !/^https?:\/\/(localhost|127\.0\.0\.1)/.test(baseURL)) return
  const browser = await chromium.launch()
  const page = await browser.newPage()
  for (const path of ['/login', '/dashboard', '/onboarding', '/vault', '/chat', '/roadmap']) {
    await page.goto(`${baseURL}${path}`, { waitUntil: 'networkidle' }).catch(() => {})
  }
  await browser.close()
}
