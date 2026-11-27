const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ['line'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:8876',
    browserName: 'chromium',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: 'python ../scripts/run_browser_e2e_server.py --port 8876',
    url: 'http://127.0.0.1:8876/api/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'PC',
      use: { viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'Tablet',
      use: { viewport: { width: 1024, height: 768 } },
    },
    {
      name: 'Smartphone',
      use: { viewport: { width: 390, height: 844 }, isMobile: true },
    },
  ],
});
