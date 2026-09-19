import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  // *.capture.ts is tooling (bun run qa:evidence), not part of the check suite
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.TEST_APP_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry'
  },
  webServer: {
    command: 'bun run start',
    url: process.env.TEST_APP_URL ?? 'http://localhost:3000',
    reuseExistingServer: !process.env.CI
  }
});
