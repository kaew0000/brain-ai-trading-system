// ============================================================
// Playwright E2E configuration
// Place in dashboard/playwright.config.ts
// ============================================================

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './src/pages/world/tests',
  testMatch: '**/*.e2e.spec.ts',
  fullyParallel: false,
  retries: 1,
  workers: 1,
  timeout: 30_000,

  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
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
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },

  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
});
