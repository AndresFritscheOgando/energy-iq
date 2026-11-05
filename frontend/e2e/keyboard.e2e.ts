/** A keyboard only run through the meter page (spec 0011 child 0003 AC-7). */
import { SHARED_STATE, createMeter, expect, test, waitForPlot } from "./support";

test.use({ storageState: SHARED_STATE });

test("create a reading, handle the warning, cancel a void, move through the chart", async ({
  page,
}) => {
  await page.goto("/");
  const { meterId } = await createMeter(page, [
    [30, "100"],
    [20, "150"],
    [10, "200"],
  ]);
  await page.goto(`/meters/${meterId}`);
  await waitForPlot(page);

  // The form is first in the page's tab order after the header and breadcrumb.
  await page.getByLabel("Meter value").focus();
  await page.keyboard.type("210");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Reading saved")).toBeVisible();
  await expect(page.getByLabel("Meter value")).toBeFocused();

  // A lower value: focus moves to the warning, nothing is saved yet.
  await page.keyboard.type("5");
  await page.keyboard.press("Enter");
  const warning = page.getByRole("alert").filter({ hasText: "Lower than an earlier reading" });
  await expect(warning).toBeFocused();
  await page.keyboard.press("Tab"); // the link
  await page.keyboard.press("Tab"); // Save anyway
  await page.keyboard.press("Tab"); // Change value
  await expect(page.getByRole("button", { name: "Change value" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(warning).toHaveCount(0);
  await expect(page.getByLabel("Meter value")).toBeFocused();

  // Open and cancel a void, with focus returning to the same action.
  const action = page.getByRole("button", { name: /^Void 210 kWh/ });
  await action.focus();
  await expect(action).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(action).toBeFocused();

  // One tab stop for the chart; arrows, Home, and End move the readout.
  const chart = page.getByTestId("usage-chart");
  const readout = page.getByTestId("chart-readout");
  await chart.focus();
  await page.keyboard.press("Home");
  const first = await readout.innerText();
  await page.keyboard.press("ArrowRight");
  await expect(readout).not.toHaveText(first);
  await page.keyboard.press("ArrowLeft");
  await expect(readout).toHaveText(first);
  await page.keyboard.press("End");
  await expect(readout).not.toHaveText(first);
  await expect(readout).toHaveAttribute("aria-live", "polite");

  const outline = await chart.evaluate((node) => getComputedStyle(node).outlineStyle);
  expect(outline).not.toBe("none");
});
