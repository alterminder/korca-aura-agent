import { test, expect } from '@playwright/test';

test.describe('Dashboard & Core Pages Smoke Test', () => {
  test.beforeEach(async ({ page }) => {
    // 1. Establish full mock wrappers to completely sandbox the API
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ authenticated: true }),
      });
    });

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

    await page.route('**/api/documents?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/users', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'user-1',
            email: 'expert-one@example.com',
            name: 'Expert One',
            title: 'Senior Support',
            department: 'Support',
            manager_name: null,
            manager_email: null,
            certifications: [],
            tickets_resolved: 42,
            topics: ['React', 'Neo4j'],
            skills: ['debugging', 'cypher'],
          },
        ]),
      });
    });

    await page.route('**/api/clients?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            name: 'Acme Corp',
            display_name: 'Acme Corporation',
            domain: 'acme.com',
            ticket_count: 5,
            agents: [],
            tickets: [],
            parent_domain: null,
            parent_name: null,
          },
        ]),
      });
    });

    await page.route('**/api/import/teamwork/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tickets_in_graph: 100, import_running: false, last_imported_at: null }),
      });
    });

    await page.route('**/api/import/teamwork/routing-mode', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ mode: 'manual' }),
      });
    });

    await page.route('**/api/import/teamwork/sync-state', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ initialized: true, state: null }),
      });
    });

    await page.route('**/api/import/teamwork/auto-sync', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ enabled: false, interval_seconds: 300 }),
      });
    });

    await page.route('**/api/import/staged?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tickets: [], total: 0 }),
      });
    });

    await page.route('**/api/import/routing/ai-accuracy', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ evaluated: 0, correct: 0, accuracy_pct: null }),
      });
    });

    await page.route('**/api/aura/agents', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    // Sandbox destructive mutations
    await page.route('**/api/import/teamwork/tickets', async (route) => {
      if (route.request().method() === 'DELETE') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ deleted: 0, status: 'sandboxed' }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route('**/api/import/teamwork/purge-blocked', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ deleted: 0, status: 'sandboxed' }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route('**/api/documents/*', async (route) => {
      if (route.request().method() === 'DELETE') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'sandboxed' }),
        });
      } else {
        await route.continue();
      }
    });

    // 2. Perform automated login
    await page.goto('/');
  });

  test('verifies Dashboard rendering and navigates through core application pages', async ({ page }) => {
    // ---- DASHBOARD ----
    await expect(page.locator('h1:has-text("Dashboard")')).toBeVisible();
    await expect(page.locator('text=Recent Routing Activity')).toBeVisible();
    await expect(page.locator('text=Aura Accuracy')).toBeVisible();

    // ---- DOCUMENTS ----
    await page.click('a[href="/documents"]');
    await expect(page.locator('h1')).toHaveText('Documents');
    await expect(page.locator('input[placeholder*="Search"]')).toBeVisible();

    // ---- EXPERTS ----
    await page.click('a[href="/experts"]');
    await expect(page.locator('h1')).toHaveText('Experts');
    await expect(page.locator('text=expert-one@example.com')).toBeVisible();
    await expect(page.locator('text=tickets resolved')).toBeVisible();

    // ---- CLIENTS ----
    await page.click('a[href="/clients"]');
    await expect(page.locator('h1')).toHaveText('Clients');
    await expect(page.locator('text=acme.com')).toBeVisible();
    await expect(page.locator('text=Acme Corporation')).toBeVisible();

    // ---- INTEGRATIONS ----
    await page.click('a[href="/integrations"]');
    await expect(page.locator('h1')).toHaveText('Integrations');
    await expect(page.locator('text=Teamwork Desk')).toBeVisible();

    // ---- ROUTING PLAYGROUND ----
    await page.click('a[href="/routing"]');
    await expect(page.locator('h1')).toHaveText('Routing Sandbox');
    await expect(page.locator('button:has-text("Run Agent")')).toBeVisible();
  });
});
