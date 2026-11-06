/** Manual invoice confirmation and revision history in a real browser. */

import { SHARED_STATE, createMeter, daysAgo, expect, test } from "./support";

test.use({ storageState: SHARED_STATE });

test("a manual invoice is reviewed, confirmed, and corrected", async ({ page }) => {
  const { meterId } = await createMeter(page);
  await page.goto(`/meters/${meterId}`);
  const invoices = page.getByRole("region", { name: "Invoices" });
  await expect(invoices.getByText("No invoices have been saved for this meter.")).toBeVisible();
  await invoices.getByLabel("Period start", { exact: true }).fill(daysAgo(30));
  await invoices.getByLabel("Period end", { exact: true }).fill(daysAgo(1));
  await invoices.getByLabel("Billed use (kWh)").fill("123.456789");
  await invoices.getByLabel("Invoice total (DOP)").fill("999.01");
  await invoices.getByRole("button", { name: "Save draft" }).click();
  await expect(
    invoices.getByText("Draft saved. Review the values, then confirm it."),
  ).toBeVisible();
  await expect(invoices.getByText("123.456789 kWh · DOP 999.01")).toBeVisible();
  await expect(invoices.getByText("123.456789 (manual)")).toBeVisible();
  await invoices.getByRole("button", { name: "Edit draft" }).click();
  await invoices.getByLabel("Energy charge (DOP, optional)").last().fill("500.00");
  await invoices.getByRole("button", { name: "Save draft changes" }).click();
  await expect(invoices.getByText(/Draft updated/)).toBeVisible();
  await expect(invoices.getByText("500.00 (manual)")).toBeVisible();
  await invoices.getByRole("button", { name: "Confirm revision" }).click();
  await expect(invoices.getByText("Invoice confirmed.")).toBeVisible();
  await invoices.getByRole("button", { name: "Correct values" }).click();
  await invoices.getByLabel("Invoice total (DOP)").last().fill("1001.02");
  await invoices.getByRole("button", { name: "Save correction" }).click();
  await expect(
    invoices.getByText("Correction saved as a draft. Review and confirm it."),
  ).toBeVisible();
  await invoices.getByRole("button", { name: "Confirm revision" }).click();
  await expect(invoices.getByText("Invoice confirmed.")).toBeVisible();
  await invoices.getByText("Revision history").click();
  await expect(invoices.getByText(/Revision 2, earlier confirmed, DOP 999.01/)).toBeVisible();
  await expect(invoices.getByText(/Revision 1, superseded draft, DOP 999.01/)).toBeVisible();
  await expect(invoices.getByText(/Revision 3, current, DOP 1001.02/)).toBeVisible();
});

test("a partial draft is completed in steps and confirmed", async ({ page }) => {
  const { meterId } = await createMeter(page);
  await page.goto(`/meters/${meterId}`);
  const invoices = page.getByRole("region", { name: "Invoices" });
  await invoices.getByLabel("Invoice total (DOP)").fill("10.50");
  await invoices.getByRole("button", { name: "Save draft" }).click();
  await expect(invoices.getByText(/Draft saved/)).toBeVisible();
  await invoices.getByRole("button", { name: "Confirm revision" }).click();
  await expect(invoices.getByText("Complete the required values before confirming.")).toBeVisible();
  for (const [label, value] of [
    ["Period start", daysAgo(30)],
    ["Period end", daysAgo(1)],
    ["Billed use (kWh)", "100"],
  ] as const) {
    await invoices.getByRole("button", { name: "Edit draft" }).click();
    await invoices.getByLabel(label, { exact: true }).last().fill(value);
    await invoices.getByRole("button", { name: "Save draft changes" }).click();
    await expect(invoices.getByText(/Draft updated/)).toBeVisible();
  }
  await invoices.getByRole("button", { name: "Confirm revision" }).click();
  await expect(invoices.getByText("Invoice confirmed.")).toBeVisible();
});
