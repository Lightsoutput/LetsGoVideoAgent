import { defineConfig, devices } from "@playwright/test";

const useExternalServer = process.env.E2E_EXTERNAL_SERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 15_000,
  use: {
    baseURL: "http://127.0.0.1:3000",
    channel: "chrome",
    viewport: { width: 1440, height: 1000 },
    trace: "on-first-retry",
  },
  webServer: useExternalServer
    ? undefined
    : {
        command:
          '"D:\\Tools\\NodeJs\\node.exe" node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3000',
        env: {
          NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8000/api/v1",
        },
        url: "http://127.0.0.1:3000",
        reuseExistingServer: true,
        timeout: 20_000,
      },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
