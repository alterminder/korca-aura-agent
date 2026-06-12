import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:5173';

// CRITICAL GUARD: Ensure tests never run against production contexts
if (!baseURL.includes('localhost') && !baseURL.includes('127.0.0.1')) {
  throw new Error(`CRITICAL GUARD: Playwright tests are blocked from running against production URL contexts: ${baseURL}`);
}

export default defineConfig({
  testDir: './e2e',
  timeout: 30 * 1000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Keep single worker locally to maintain clean session alignment
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    viewport: { width: 1280, height: 720 },
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    stdout: 'ignore',
    stderr: 'pipe',
    timeout: 60 * 1000,
  },
});
