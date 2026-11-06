/**
 * The invoice review pass in a real browser (spec 0012 child 0005 AC-2 to AC-5):
 * keyboard flow, confirmation, a stale answer, and source download authorization.
 */
import { request as playwrightRequest } from "@playwright/test";

import { createDraft, sharedSource } from "./invoice-support";
import { PRISTINE_STATE, SHARED_STATE, createMeter, daysAgo, expect, test } from "./support";

test.use({ storageState: SHARED_STATE });

test("a draft is completed and confirmed with the keyboard alone", async ({ page }) => {
  const { meterId } = await createMeter(page);
  const made = await createDraft(page, meterId);
  await page.goto(`/invoices/${made.id}`);
  await expect(page.getByRole("heading", { name: "Invoice values" })).toBeVisible();

  // Confirming now names every missing field and sends nothing.
  await page.getByRole("button", { name: "Confirm this revision" }).focus();
  await page.keyboard.press("Enter");
  const blockers = page.getByRole("alert").filter({ hasText: "These values stop confirmation" });
  await expect(blockers).toContainText("Period start is missing");
  await expect(blockers).toContainText("Period end is missing");
  await expect(blockers).toContainText("Billed use (kWh) is missing");

  // Date inputs take their own Tab stops per segment, so fill them directly and
  // use the keyboard for the text field, form submit, and the buttons.
  await page.getByLabel("Period start").fill(daysAgo(30));
  await page.getByLabel("Period end").fill(daysAgo(1));
  await page.getByLabel("Billed use (kWh)").focus();
  await page.keyboard.type("200");
  await page.keyboard.press("Enter"); // submits the form: a draft, not a confirmation
  await expect(page.getByRole("status").filter({ hasText: "Saved as a draft" })).toBeVisible();
  await expect(page.getByLabel("Billed use (kWh)")).toHaveValue("200.000000");
  await expect(page.getByText("Confirmed", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Confirm this revision" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Invoice confirmed." })).toBeVisible();
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible();
});

test("a stale save keeps the edits and waits for the owner", async ({ page }) => {
  const { meterId } = await createMeter(page);
  const made = await createDraft(page, meterId, { complete: true });
  await page.goto(`/invoices/${made.id}`);
  await expect(page.getByLabel("Invoice total (DOP)")).toHaveValue("1500.25");

  // Another tab changes the invoice behind this page.
  const change = await page.request.post(`/api/v1/invoices/${made.id}/revisions`, {
    headers: { "X-EnergyIQ-CSRF": "1", "Idempotency-Key": crypto.randomUUID() },
    data: {
      base_revision_id: made.revisionId,
      expected_current_revision_id: null,
      billed_kwh: "210",
    },
  });
  expect(change.status()).toBe(201);

  await page.getByLabel("Invoice total (DOP)").fill("1600.00");
  await page.getByRole("button", { name: "Save draft changes" }).click();
  const stale = page.getByRole("alert").filter({ hasText: "changed since you opened it" });
  await expect(stale).toBeVisible();
  await expect(page.getByLabel("Invoice total (DOP)")).toHaveValue("1600.00");
  await expect(page.getByRole("button", { name: "Save draft changes" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Confirm this revision" })).toBeDisabled();

  await page.getByRole("button", { name: "Keep my edits on the latest version" }).click();
  await expect(stale).toBeHidden();
  await expect(page.getByLabel("Invoice total (DOP)")).toHaveValue("1600.00");
  await page.getByRole("button", { name: "Save draft changes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved as a draft" })).toBeVisible();
  await expect(page.getByLabel("Billed use (kWh)")).toHaveValue("210.000000");
});

test("the source is a private download and never an inline frame", async ({ page, baseURL }) => {
  const { meterId, documentId } = await sharedSource(page);
  const made = await createDraft(page, meterId, { complete: true, documentId });
  await page.goto(`/invoices/${made.id}`);

  const link = page.getByRole("link", { name: "Download the original PDF" });
  await expect(link).toHaveAttribute("href", `/api/v1/documents/${documentId}/source`);
  await expect(page.locator("iframe, embed, object")).toHaveCount(0);

  // The click downloads a file; the page stays where it is.
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  expect(download.suggestedFilename()).toBe(`bill-${documentId}.pdf`);
  expect(page.url()).toContain(`/invoices/${made.id}`);

  const url = `/api/v1/documents/${documentId}/source`;
  const owner = await page.request.get(url);
  expect(owner.status()).toBe(200);
  expect(owner.headers()["content-type"]).toBe("application/pdf");
  expect(owner.headers()["content-disposition"]).toContain("attachment");
  expect(owner.headers()["content-security-policy"]).toBe("sandbox");
  expect(owner.headers()["cache-control"]).toContain("no-store");

  const anonymous = await playwrightRequest.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] }, // the runner would otherwise reuse the signed in state
  });
  expect((await anonymous.get(url)).status()).toBe(401);
  await anonymous.dispose();

  // Another signed in account sees the same answer as for an unknown ID.
  const other = await playwrightRequest.newContext({ baseURL, storageState: PRISTINE_STATE });
  expect((await other.get(url)).status()).toBe(404);
  expect((await other.get(`/api/v1/invoices/${made.id}`)).status()).toBe(404);
  await other.dispose();
});

test("the list opens a review and the new page saves a draft", async ({ page }) => {
  const { meterId } = await createMeter(page);
  await page.goto(`/meters/${meterId}/invoices`);
  await expect(page.getByText("No invoices have been saved for this meter yet.")).toBeVisible();

  await page.getByRole("link", { name: "Enter an invoice by hand" }).click();
  await expect(page).toHaveURL(`/meters/${meterId}/invoices/new`);
  await page.getByLabel("Invoice total (DOP)").fill("42.00");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page).toHaveURL(/\/invoices\/[0-9a-f-]{36}$/);
  await expect(page.getByLabel("Invoice total (DOP)")).toHaveValue("42.00");
  await expect(page.getByText("entered by hand, so there is no source document")).toBeVisible();

  await page.goto(`/meters/${meterId}/invoices`);
  await page.getByRole("link", { name: /^Review/ }).click();
  await expect(page.getByRole("heading", { name: "Invoice values" })).toBeVisible();
});
