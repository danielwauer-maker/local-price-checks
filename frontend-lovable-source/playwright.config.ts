import { defineConfig, devices } from "@playwright/test";

const port = 4174;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env["CI"]),
  retries: process.env["CI"] ? 2 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 7_500 },
  reporter: process.env["CI"]
    ? [["line"], ["html", { open: "never" }], ["blob", { outputDir: "blob-report" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    serviceWorkers: "block",
  },
  outputDir: "test-results",
  webServer: process.env["PLAYWRIGHT_EXTERNAL_SERVER"]
    ? undefined
    : {
        command: `node ./node_modules/vite/bin/vite.js dev --host 127.0.0.1 --port ${port}`,
        url: baseURL,
        reuseExistingServer: !process.env["CI"],
        timeout: 120_000,
        env: {
          ...process.env,
          VITE_E2E_MODE: "1",
          VITE_SUPABASE_URL: `${baseURL}/__e2e/supabase`,
          VITE_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_e2e_only",
        },
      },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "desktop-firefox",
      use: {
        ...devices["Desktop Firefox"],
        viewport: { width: 1440, height: 900 },
        launchOptions: {
          firefoxUserPrefs: {
            "gfx.webrender.all": false,
            "gfx.webrender.software": false,
            "layers.acceleration.disabled": true,
          },
        },
      },
    },
    {
      name: "desktop-webkit",
      use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile-webkit",
      use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"], viewport: { width: 412, height: 915 } },
    },
  ],
});
