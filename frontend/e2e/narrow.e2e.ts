/** Narrow width smoke and reflow (spec 0011 child 0003 AC-4, AC-7). */
import { SHARED_STATE, createMeter, expect, submitReading, test, waitForPlot } from "./support";

test.use({ storageState: SHARED_STATE });

test("open the meter page and save a reading, with the form first", async ({ page }) => {
  await page.goto("/");
  const { meterId } = await createMeter(page, [
    [20, "100"],
    [10, "120"],
  ]);
  await page.goto(`/meters/${meterId}`);
  await waitForPlot(page);

  const form = await page.getByRole("form", { name: "Add a reading" }).boundingBox();
  const usage = await page.getByRole("region", { name: "Usage" }).boundingBox();
  expect(form!.y).toBeLessThan(usage!.y);

  await submitReading(page, "140", 0);
  await expect(page.getByText("Reading saved")).toBeVisible();
});

test("no sideways scroll at 320 wide, and the table scrolls in its own region", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  const { meterId } = await createMeter(page, [
    [40, "100"],
    [30, "130"],
    [10, "120"],
  ]);
  await page.goto(`/meters/${meterId}?range=365d`);
  await waitForPlot(page);

  const widths = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    window: document.documentElement.clientWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.window);

  const region = page.getByRole("region", { name: "Intervals and gaps" });
  const scrolls = await region.evaluate((node) => node.scrollWidth > node.clientWidth);
  expect(scrolls).toBe(true);
});
