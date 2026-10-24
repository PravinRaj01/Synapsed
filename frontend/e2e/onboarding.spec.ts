import { expect, test } from '@playwright/test'

// The first-time journey needs a signed-up account that has no workspace yet, so it runs once per such account.
const email = process.env.E2E_NEW_EMAIL
const password = process.env.E2E_NEW_PASSWORD

test.describe('first-time journey', () => {
  test.skip(!email || !password, 'E2E_NEW_EMAIL and E2E_NEW_PASSWORD are not set')
  test.skip(({ isMobile }) => isMobile, 'the account can only be set up once, so this runs on desktop only')

  test('a new user is sent to set up, loads the demo, sees the dashboard and asks a question', async ({ page }) => {
    test.setTimeout(150_000) // the last step waits for a live model
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    await expect(page).toHaveURL(/\/onboarding$/, { timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'Welcome to Synapsed' })).toBeVisible()
    await page.screenshot({ path: 'test-results/onboarding-1-business.png' })

    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByText('Enter your company name')).toBeVisible()
    await page.getByLabel('Company').fill('Ledgerly')
    await page.getByLabel('Industry').fill('Finance software')
    await page.getByLabel('What does your product do?').fill('Invoicing and expenses for finance teams')
    await page.getByLabel('Your role').fill('Head of Product')
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByLabel('Segment 1 name')).toHaveValue('Enterprise')
    await page.getByLabel('Campaign name').fill('Month-end research')
    await page.screenshot({ path: 'test-results/onboarding-2-campaign.png' })
    await page.getByRole('button', { name: 'Continue' }).click()

    await page.screenshot({ path: 'test-results/onboarding-3-data.png' })
    await page.getByRole('button', { name: /Explore the demo sandbox/ }).click()

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 })
    await expect(page.getByText('Insights found')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('37', { exact: true })).toBeVisible()
    await expect(page.getByText('Report exports time out').first()).toBeVisible()
    await expect(page.getByText('Customer sentiment')).toBeVisible()
    await expect(page.getByText('Review 0 sources')).toHaveCount(0)
    await page.waitForTimeout(1200) // let the count-up and bars finish
    await page.screenshot({ path: 'test-results/dashboard-light.png', fullPage: true })

    await page.getByRole('button', { name: 'Account menu' }).click()
    const toggle = page.getByRole('menuitem', { name: /theme/i })
    if (await toggle.isVisible()) await toggle.click()
    else {
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    }
    await page.waitForTimeout(400)
    await page.screenshot({ path: 'test-results/dashboard-dark.png', fullPage: true })

    await page.getByRole('button', { name: /Ask your data/ }).click()
    await page.getByRole('button', { name: 'What are customers struggling with most?' }).click()
    await expect(page.getByText('Reading your sources…')).toBeVisible()
    // The answer comes from a live model: either a cited answer or a plain refusal is a correct outcome.
    await expect(page.getByText(/^\[\d+\] /).first().or(page.getByText('Not in your sources'))).toBeVisible({ timeout: 60_000 })
    await page.screenshot({ path: 'test-results/dashboard-chat.png' })

    await page.reload()
    await expect(page).toHaveURL(/\/dashboard$/) // now has a workspace, so no more onboarding
    await expect(page.getByText('Insights found')).toBeVisible({ timeout: 30_000 })
  })
})
