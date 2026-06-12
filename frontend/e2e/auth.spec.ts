import { test, expect } from '@playwright/test';

test.describe('Authentication Flow', () => {
  let authenticated = false;

  test.beforeEach(async ({ page }) => {
    authenticated = false;

    // Intercept Me route
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ authenticated }),
      });
    });

    // Intercept Login route
    await page.route('**/api/auth/login', async (route) => {
      const request = route.request();
      const postData = JSON.parse(request.postData() || '{}');
      if (postData.password === 'password') {
        authenticated = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ authenticated: true }),
        });
      } else {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Invalid password' }),
        });
      }
    });

    // Intercept Stats / Recent Activity to avoid empty or failing fetches on Dashboard load
    await page.route('**/api/stats', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ documents: 10, users: 5, tickets: 45, clients: 12 }),
      });
    });

    await page.route('**/api/stats/recent-activity', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/stats/expert-load', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/stats/client-load', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/stats/needs-review', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ staged: 0 }),
      });
    });
  });

  test('redirects unauthenticated users to login and enforces valid credentials', async ({ page }) => {
    // Navigate to root path (which triggers auth gate loading)
    await page.goto('/');

    // Verify redirects to Sign In page
    await expect(page.locator('h1')).toHaveText('Korca');
    await expect(page.locator('p')).toHaveText('Sign in to continue');

    // Test invalid password submission
    const passwordInput = page.locator('#korca-password');
    await passwordInput.fill('wrong_password');
    await page.click('button[type="submit"]');

    // Check validation feedback
    await expect(page.locator('text=Invalid password')).toBeVisible();

    // Test valid password submission
    await passwordInput.fill('password');
    await page.click('button[type="submit"]');

    // Verify we have successfully passed the gate and navigated to the Dashboard
    await expect(page.locator('h1:has-text("Dashboard")')).toBeVisible();
    await expect(page.locator('text=Recent Routing Activity')).toBeVisible();
  });
});
