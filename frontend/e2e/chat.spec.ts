import { expect, test } from '@playwright/test'

// Needs a signed-in account whose active campaign has approved sources (the demo sandbox is enough).
const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD

test.describe('deep workspace', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')

  test('ask a question, follow a footnote to the quote in its source', async ({ page, isMobile }) => {
    test.setTimeout(150_000)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 })

    await page.getByRole('link', { name: 'Chat', exact: true }).click()
    await expect(page).toHaveURL(/\/chat$/)
    if (!isMobile) {
      await expect(page.getByText('Read the evidence')).toBeVisible({ timeout: 30_000 })
      await expect(page.getByLabel(/^Use /).first()).toBeChecked()
    }
    await page.screenshot({ path: `test-results/chat-1-empty${isMobile ? '-phone' : ''}.png` })

    await page.getByRole('button', { name: 'What are customers struggling with most?' }).click()
    await expect(page.getByText('Reading your sources…')).toBeVisible()
    // A live model: a cited answer or a plain refusal are both correct outcomes, an error is not.
    const footnote = page.getByRole('button', { name: /^Show source \d+:/ }).first()
    await expect(footnote.or(page.getByText('Not in your sources'))).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(footnote).toBeVisible()
    await expect(page.getByTestId('telemetry')).toContainText('passages read')
    await page.screenshot({ path: `test-results/chat-2-answer${isMobile ? '-phone' : ''}.png` })

    await footnote.click()
    const text = page.getByTestId('source-text')
    await expect(text).toBeVisible({ timeout: 30_000 })
    await expect(text.locator('[data-focus]')).toBeVisible()
    await expect(text.locator('[data-focus]')).not.toBeEmpty()
    await page.screenshot({ path: `test-results/chat-3-quote${isMobile ? '-phone' : ''}.png` })

    // The conversation is still there after visiting another page.
    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/)
    await page.getByRole('link', { name: 'Chat', exact: true }).click()
    if (isMobile) await page.getByRole('tab', { name: 'Chat' }).click()
    await expect(page.getByText('What are customers struggling with most?').first()).toBeVisible()
  })
})
