import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:4321', channel: process.env.PLAYWRIGHT_CHANNEL || undefined },
  webServer: {
    command: 'npm run preview',
    url: 'http://127.0.0.1:4321/ru/',
    env: { ASTRO_TELEMETRY_DISABLED: '1' },
    reuseExistingServer: !process.env.CI,
  },
});
