/**
 * Axe and reflow for the invoice screens (spec 0012 child 0005 AC-5), in light
 * and dark. Both projects run this file, so it covers desktop and 390 wide.
 */
import { createDraft, sharedSource } from "./invoice-support";
import { SHARED_STATE, createMeter, expect, expectNoAxeViolations, test } from "./support";

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`invoice screens, ${colorScheme}`, () => {
    test.use({ storageState: SHARED_STATE, colorScheme });

    test("list, new, and review states", async ({ page }) => {
      await page.goto("/");
      const { meterId } = await createMeter(page);

      await page.goto(`/meters/${meterId}/invoices`);
      await expect(page.getByText("No invoices have been saved for this meter yet.")).toBeVisible();
      await expectNoAxeViolations(page);

      await page.goto(`/meters/${meterId}/invoices/new`);
      await expect(page.getByRole("button", { name: "Save draft" })).toBeVisible();
      await expectNoAxeViolations(page);

      const source = await sharedSource(page);
      const made = await createDraft(page, source.meterId, { documentId: source.documentId });

      await page.goto(`/meters/${source.meterId}/invoices`);
      await expect(page.getByRole("link", { name: /^Review/ }).first()).toBeVisible();
      await expectNoAxeViolations(page);

      await page.goto(`/invoices/${made.id}`);
      await expect(page.getByRole("link", { name: "Download the original PDF" })).toBeVisible();
      await expectNoAxeViolations(page);

      // The blocker list and an unsaved edit alert are real states of this page.
      await page.getByRole("button", { name: "Confirm this revision" }).click();
      await expect(page.getByText("These values stop confirmation:")).toBeVisible();
      await expectNoAxeViolations(page);

      await page.getByLabel("Invoice total (DOP)").fill("1.00");
      await page.getByRole("button", { name: "Confirm this revision" }).click();
      await expect(page.getByText(/unsaved edits/i)).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("stale conflict and a confirmed invoice", async ({ page }) => {
      await page.goto("/");
      const { meterId } = await createMeter(page);
      const made = await createDraft(page, meterId, { complete: true });
      await page.goto(`/invoices/${made.id}`);
      await expect(page.getByLabel("Invoice total (DOP)")).toHaveValue("1500.25");
      const change = await page.request.post(`/api/v1/invoices/${made.id}/revisions`, {
        headers: { "X-EnergyIQ-CSRF": "1", "Idempotency-Key": crypto.randomUUID() },
        data: {
          base_revision_id: made.revisionId,
          expected_current_revision_id: null,
          billed_kwh: "211",
        },
      });
      expect(change.status()).toBe(201);
      await page.getByLabel("Invoice total (DOP)").fill("1.50");
      await page.getByRole("button", { name: "Save draft changes" }).click();
      await expect(page.getByText(/changed since you opened it/)).toBeVisible();
      await expectNoAxeViolations(page);

      await page.getByRole("button", { name: "Discard my edits and use the latest" }).click();
      await expect(page.getByLabel("Billed use (kWh)")).toHaveValue("211.000000");
      await page.getByRole("button", { name: "Confirm this revision" }).click();
      await expect(page.getByText("Invoice confirmed.")).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("proposal conflicts on the review page", async ({ page }) => {
      await page.goto("/");
      const source = await sharedSource(page);
      const made = await createDraft(page, source.meterId, { documentId: source.documentId });
      const field = (name: string, extra: object = {}) => ({
        name,
        state: "not_found",
        value: null,
        quote: null,
        page_number: null,
        uncertainty: null,
        issues: [],
        evidence_verified: false,
        ...extra,
      });
      // No worker runs here, so the extraction answer is a fixed synthetic body.
      await page.route(`**/api/v1/documents/${source.documentId}/extractions`, (route) =>
        route.fulfill({
          json: {
            items: [
              {
                run_id: "r",
                run_number: 1,
                model: "synthetic",
                prompt_version: "p",
                finished_at: "2026-11-05T15:00:00Z",
                proposal: {
                  fields: [field("billed_kwh", { issues: ["contradiction"] })],
                  contradictions: [
                    {
                      field: "billed_kwh",
                      candidates: [
                        {
                          value: "250",
                          raw_value: "250",
                          quote: "Consumo: 250 kWh",
                          page_number: 1,
                        },
                        { value: "260", raw_value: "260", quote: "Total kWh: 260", page_number: 2 },
                      ],
                    },
                  ],
                  conflicts: [{ code: "contradiction", fields: ["billed_kwh"] }],
                  requires_review: true,
                },
              },
            ],
            next_cursor: null,
          },
        }),
      );
      await page.goto(`/invoices/${made.id}`);
      const group = page.getByRole("group", { name: "Needs your attention" });
      await expect(group).toContainText("Billed use (kWh): the bill shows more than one value.");
      await expect(page.getByText("Total kWh: 260")).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("no sideways scroll at 320 wide", async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 700 });
      await page.goto("/");
      const { meterId, documentId } = await sharedSource(page);
      const made = await createDraft(page, meterId, { complete: true, documentId });
      for (const path of [
        `/meters/${meterId}/invoices`,
        `/meters/${meterId}/invoices/new`,
        `/invoices/${made.id}`,
      ]) {
        await page.goto(path);
        await expect(page.getByRole("main")).toBeVisible();
        const widths = await page.evaluate(() => ({
          document: document.documentElement.scrollWidth,
          window: document.documentElement.clientWidth,
        }));
        expect(widths.document, path).toBeLessThanOrEqual(widths.window);
      }
    });
  });
}
