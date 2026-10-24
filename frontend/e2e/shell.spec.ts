import { expect, test } from '@playwright/test'

const email = process.env.E2E_EMAIL
const password = process.env.E2E_PASSWORD

test.describe('signed out', () => {
  test('a protected page sends you to sign in', async ({ page }) => {
    await page.goto('/vault')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  })

  test('the form checks the fields before asking the service', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill('not-an-email')
    await page.getByLabel('Password').fill('short')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText('Enter a valid email address')).toBeVisible()
    await expect(page.getByText('Use at least 8 characters')).toBeVisible()
  })

  test('creating an account asks for a name', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('tab', { name: 'Create account' }).click()
    await expect(page.getByLabel('Your name')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible()
  })

  test('the sign-in page works in both themes', async ({ page }) => {
    await page.goto('/login')
    for (const theme of ['light', 'dark']) {
      await page.evaluate((t) => (document.documentElement.dataset.theme = t), theme)
      await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible()
    }
  })

  test('a wrong password shows a readable message and stays put', async ({ page }) => {
    test.skip(!email, 'E2E_EMAIL is not set')
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill('definitely-the-wrong-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid/i)
    await expect(page).toHaveURL(/\/login$/)
  })
})

test.describe('signed in', () => {
  test.skip(!email || !password, 'E2E_EMAIL and E2E_PASSWORD are not set')

  test('sign in lands on the page you were heading for, keeps you signed in across a reload, and sign out locks the pages again', async ({ page }) => {
    await page.goto('/vault')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/vault$/, { timeout: 20_000 })

    await page.reload()
    await expect(page).toHaveURL(/\/vault$/)
    await expect(page.getByRole('heading', { name: 'Knowledge Vault' })).toBeVisible()

    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('the dashboard loads real campaign numbers without a storm of failing requests', async ({ page }) => {
    const refused: string[] = []
    page.on('response', (r) => { if (r.status() === 401 && r.url().includes('/api/')) refused.push(r.url()) })
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 20_000 })
    await expect(page.getByText(/Insights found|first campaign/)).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2000)
    expect(refused, 'the API refused our token').toEqual([])
  })

  test('the theme choice survives a reload', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(email!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 20_000 })
    await page.getByRole('button', { name: 'Account menu' }).click()
    const toggle = page.getByRole('menuitem', { name: /theme/i })
    if (await toggle.isVisible()) await toggle.click()
    else { await page.keyboard.press('Escape'); await page.getByRole('button', { name: 'Switch to dark theme' }).click() }
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })
})
