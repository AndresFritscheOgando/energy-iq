import { execFileSync } from "node:child_process";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { API_ORIGIN, API_PORT, APP_ORIGIN, APP_PORT, BUILD_ENV } from "./e2e/constants.mjs";

/**
 * Spec 0011 child 0003 AC-1, AC-3: Chromium, no retries, one worker, and servers
 * that are never reused, so a result can't depend on your dev servers.
 */
const REPO = path.resolve(__dirname, "..");

function databaseUrls(): { app: string; migrator: string } {
  // Playwright loads this file more than once; ask Python only the first time.
  if (!process.env.E2E_DATABASE_URLS) {
    process.env.E2E_DATABASE_URLS = execFileSync(
      "uv",
      [
        "run",
        "python",
        "backend/scripts/reset_e2e_db.py",
        "--database",
        "energyiq_e2e",
        "--print-urls",
      ],
      { cwd: REPO, encoding: "utf8", shell: process.platform === "win32" },
    );
  }
  return JSON.parse(process.env.E2E_DATABASE_URLS);
}

const urls = databaseUrls();

const API_ENV = {
  ENERGYIQ_ENV: "test",
  ENERGYIQ_DATABASE_URL: urls.app,
  ENERGYIQ_MIGRATION_DATABASE_URL: urls.migrator,
  ENERGYIQ_TRUSTED_ORIGINS: JSON.stringify([APP_ORIGIN]),
};

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: APP_ORIGIN,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /setup\.e2e\.ts/ },
    {
      name: "desktop",
      dependencies: ["setup"],
      testMatch: /\.e2e\.ts$/,
      testIgnore: /(setup|narrow)\.e2e\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
    },
    {
      name: "narrow",
      dependencies: ["setup"],
      testMatch: /(narrow|axe)\.e2e\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: `uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log --no-proxy-headers --port ${API_PORT}`,
      cwd: REPO,
      url: `${API_ORIGIN}/health`,
      reuseExistingServer: false,
      env: API_ENV,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `pnpm exec next start -p ${APP_PORT}`,
      cwd: __dirname,
      url: `${APP_ORIGIN}/login`,
      reuseExistingServer: false,
      env: BUILD_ENV,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
