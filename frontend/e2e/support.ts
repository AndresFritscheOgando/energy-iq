/**
 * Shared end to end helpers (spec 0011 child 0003). Each test creates its own
 * property, because every test shares one database for the run. Synthetic data
 * only.
 */
import { randomBytes } from "node:crypto";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";

const STATE_DIR = path.join(__dirname, "..", "test-results", ".auth");
export const SHARED_STATE = path.join(STATE_DIR, "shared.json");
export const PRISTINE_STATE = path.join(STATE_DIR, "pristine.json");
export const SHARED_INFO = path.join(STATE_DIR, "shared-info.json");

export const PASSWORD = "e2e-password-synthetic-only";
const ZONE = "America/Santo_Domingo";
const CSRF = { "X-EnergyIQ-CSRF": "1" };

/** Any 429 fails the test (AC-4): the suite must stay inside the rate limits. */
export const test = base.extend<{ noRateLimits: void }>({
  noRateLimits: [
    async ({ page }, provide) => {
      const limited: string[] = [];
      page.on("response", (response) => {
        if (response.status() === 429) {
          limited.push(response.url());
        }
      });
      await provide();
      expect(limited, "no request may hit a rate limit").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export function uniqueName(prefix: string): string {
  return `${prefix} ${randomBytes(4).toString("hex")}`;
}

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${randomBytes(6).toString("hex")}@example.test`;
}

/** A plain date in the property's default zone, `days` before today. */
export function daysAgo(days: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE }).format(new Date());
  const [year, month, day] = today.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day - days)).toISOString().slice(0, 10);
}

async function ok<T>(response: Awaited<ReturnType<APIRequestContext["post"]>>): Promise<T> {
  expect(response.ok(), `${response.url()} answered ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

export type Setup = { propertyId: string; meterId: string; nickname: string; label: string };

/** A new property and meter through the API, with the page's signed in cookies. */
export async function createMeter(page: Page, readings: [number, string][] = []): Promise<Setup> {
  const nickname = uniqueName("Home");
  const label = uniqueName("Meter");
  const property = await ok<{ id: string }>(
    await page.request.post("/api/v1/properties", { headers: CSRF, data: { nickname } }),
  );
  const meter = await ok<{ id: string }>(
    await page.request.post(`/api/v1/properties/${property.id}/meters`, {
      headers: CSRF,
      data: { label, distributor: "EDESUR" },
    }),
  );
  for (const [days, value] of readings) {
    await addReading(page, meter.id, days, value);
  }
  return { propertyId: property.id, meterId: meter.id, nickname, label };
}

export async function addReading(
  page: Page,
  meterId: string,
  days: number,
  value: string,
): Promise<string> {
  const reading = await ok<{ id: string }>(
    await page.request.post(`/api/v1/meters/${meterId}/readings`, {
      headers: CSRF,
      data: { local_date: daysAgo(days), cumulative_kwh: value },
    }),
  );
  return reading.id;
}

export async function deactivate(page: Page, meterId: string): Promise<void> {
  await ok(await page.request.post(`/api/v1/meters/${meterId}/deactivate`, { headers: CSRF }));
}

/** Type a value and optional date into the reading form, then submit it. */
export async function submitReading(page: Page, value: string, days?: number): Promise<void> {
  await page.getByLabel("Meter value").fill(value);
  if (days !== undefined) {
    await page.getByLabel("Date").fill(daysAgo(days));
  }
  await page.getByRole("button", { name: "Save reading" }).click();
}

export function chart(page: Page) {
  return page.getByTestId("usage-chart");
}

/** Recharts draws after a lazy load and a measure; wait for the plot itself. */
export async function waitForPlot(page: Page): Promise<void> {
  await expect(chart(page).locator("svg.recharts-surface")).toBeVisible();
}

/** A flat line has no height, so Playwright calls it hidden; check its path. */
export async function expectStepDrawn(page: Page): Promise<void> {
  await expect(chart(page).locator(".chart-step path").first()).toHaveAttribute("d", /^M.*L/);
}

export function intervals(page: Page) {
  return page.getByRole("region", { name: "Intervals and gaps" }).getByRole("table");
}

export async function expectNoAxeViolations(page: Page): Promise<void> {
  // A dialog fading in or a button mid transition has no settled color yet.
  await page.evaluate(() =>
    Promise.allSettled(document.getAnimations().map((animation) => animation.finished)),
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.flatMap((item) =>
      item.nodes.map((node) => `${item.id}: ${node.failureSummary} ${node.html.slice(0, 300)}`),
    ),
  ).toEqual([]);
}
