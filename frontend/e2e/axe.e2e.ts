/**
 * Axe on every listed screen and state, in light and dark, at both widths
 * (spec 0011 child 0003 AC-6). Both projects run this file. Loading states and
 * the first page failure are covered with `vitest-axe`. No exclusions.
 */
import type { Page } from "@playwright/test";

import {
  PRISTINE_STATE,
  SHARED_STATE,
  createMeter,
  deactivate,
  expect,
  expectNoAxeViolations,
  submitReading,
  test,
  waitForPlot,
} from "./support";

const SCHEMES = ["light", "dark"] as const;

for (const colorScheme of SCHEMES) {
  test.describe(`axe, ${colorScheme}`, () => {
    test.use({ colorScheme });

    test.describe("signed out", () => {
      test.use({ storageState: { cookies: [], origins: [] } });

      for (const path of ["/login", "/register"]) {
        test(path, async ({ page }) => {
          await page.goto(path);
          await expect(page.getByRole("button").first()).toBeVisible();
          await expectNoAxeViolations(page);
        });
      }
    });

    test.describe("empty account", () => {
      test.use({ storageState: PRISTINE_STATE });

      test("home, empty", async ({ page }) => {
        await page.goto("/");
        await expect(page.getByRole("heading", { name: "No properties yet" })).toBeVisible();
        await expectNoAxeViolations(page);
      });
    });

    test.describe("account with data", () => {
      test.use({ storageState: SHARED_STATE });

      /** A meter with the usual shapes: steps, a drop, and gaps. */
      const partial = (page: Page) =>
        createMeter(page, [
          [40, "100"],
          [30, "130"],
          [20, "130"],
          [10, "120"],
          [5, "140"],
        ]);

      test("home, filled", async ({ page }) => {
        await page.goto("/");
        await createMeter(page);
        await page.reload();
        await expect(page.getByRole("list", { name: "Your properties" })).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("property, empty and filled, plus not found", async ({ page }) => {
        await page.goto("/");
        const made = await createMeter(page);
        await page.goto(`/properties/${made.propertyId}`);
        await expect(page.getByRole("link", { name: new RegExp(made.label) })).toBeVisible();
        await expectNoAxeViolations(page);

        const nickname = `Empty ${made.propertyId.slice(0, 8)} ${colorScheme}`;
        await page.goto("/");
        await page.getByLabel("Nickname").fill(nickname);
        await page.getByRole("button", { name: "Add property" }).click();
        await expect(page.getByRole("heading", { name: "No meters yet" })).toBeVisible();
        await expectNoAxeViolations(page);

        await page.goto("/meters/00000000-0000-4000-8000-000000000000");
        await expect(
          page.getByRole("heading", { name: "We couldn't find that page." }),
        ).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("meter, needs readings", async ({ page }) => {
        await page.goto("/");
        const { meterId } = await createMeter(page, [[5, "10"]]);
        await page.goto(`/meters/${meterId}`);
        await expect(
          page.getByRole("heading", { name: "Add at least two readings to see usage" }),
        ).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("meter, nothing measured", async ({ page }) => {
        await page.goto("/");
        const { meterId } = await createMeter(page, [
          [200, "100"],
          [190, "150"],
        ]);
        await page.goto(`/meters/${meterId}?range=30d`);
        await waitForPlot(page);
        await expect(page.getByText("No usage is measured in the last 30 days.")).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("meter, partial, form error, warning, void dialog", async ({ page }) => {
        await page.goto("/");
        const { meterId } = await partial(page);
        await page.goto(`/meters/${meterId}`);
        await waitForPlot(page);
        await expectNoAxeViolations(page);

        await submitReading(page, "not a number");
        await expect(page.getByText("Use digits and up to 6 decimals")).toBeVisible();
        await expectNoAxeViolations(page);

        await submitReading(page, "1");
        await expect(page.getByText("Lower than an earlier reading")).toBeVisible();
        await expectNoAxeViolations(page);

        await page.getByRole("button", { name: "Change value" }).click();
        await page.getByRole("button", { name: /^Void 140 kWh/ }).click();
        await expect(page.getByRole("alertdialog")).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("meter, couldn't refresh", async ({ page }) => {
        await page.goto("/");
        const { meterId } = await partial(page);
        await page.goto(`/meters/${meterId}`);
        await waitForPlot(page);
        await page.route(`**/api/v1/meters/${meterId}/consumption*`, (route) =>
          route.fulfill({
            status: 500,
            contentType: "application/problem+json",
            body: JSON.stringify({ code: "internal_error", request_id: "e2e-ref-axe" }),
          }),
        );
        await submitReading(page, "150", 0);
        await expect(page.getByText("Out of date")).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("meter, inactive", async ({ page }) => {
        await page.goto("/");
        const { meterId } = await partial(page);
        await deactivate(page, meterId);
        await page.goto(`/meters/${meterId}`);
        await waitForPlot(page);
        await expect(page.getByRole("heading", { name: "This meter is inactive" })).toBeVisible();
        await expect(page.getByRole("button", { name: /^Void 140 kWh/ })).toBeVisible();
        await expectNoAxeViolations(page);
      });
    });
  });
}
