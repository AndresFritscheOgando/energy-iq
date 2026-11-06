/** Helpers for the invoice review pass (spec 0012 child 0005 AC-5). Synthetic data only. */
import { randomUUID } from "node:crypto";

import type { Page } from "@playwright/test";

import { createMeter, daysAgo, expect } from "./support";

const CSRF = { "X-EnergyIQ-CSRF": "1" };

/** A tiny valid PDF: the signature, one empty page, and an end marker. */
const PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" +
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n" +
    "trailer<</Root 1 0 R/Size 4>>\n%%EOF\n",
);

export async function uploadPdf(page: Page, meterId: string): Promise<string> {
  const response = await page.request.post(`/api/v1/meters/${meterId}/documents`, {
    headers: { ...CSRF, "Idempotency-Key": randomUUID() },
    multipart: { file: { name: "bill.pdf", mimeType: "application/pdf", buffer: PDF } },
  });
  expect(response.status(), await response.text()).toBe(201);
  return ((await response.json()) as { id: string }).id;
}

export type Made = { id: string; revisionId: string };

/** A draft through the API. `complete` fills every required value. */
export async function createDraft(
  page: Page,
  meterId: string,
  options: { complete?: boolean; documentId?: string } = {},
): Promise<Made> {
  const data: Record<string, unknown> = { distributor: "EDESUR", total_dop: "1500.25" };
  if (options.complete) {
    Object.assign(data, {
      period_start: daysAgo(30),
      period_end: daysAgo(1),
      billed_kwh: "200",
    });
  }
  if (options.documentId) data.source_document_id = options.documentId;
  const response = await page.request.post(`/api/v1/meters/${meterId}/invoices`, {
    headers: { ...CSRF, "Idempotency-Key": randomUUID() },
    data,
  });
  expect(response.status(), await response.text()).toBe(201);
  const body = (await response.json()) as { id: string; revisions: { id: string }[] };
  return { id: body.id, revisionId: body.revisions.at(-1)!.id };
}

let source: Promise<{ meterId: string; documentId: string }> | undefined;

/**
 * One uploaded document for the whole run. The owner may hold three active
 * documents, no worker runs here, and a document linked to an invoice cannot
 * be deleted, so every test that needs a source shares this meter and file.
 * Tests on it only create drafts and never confirm, so periods cannot overlap.
 */
export function sharedSource(page: Page): Promise<{ meterId: string; documentId: string }> {
  source ??= (async () => {
    const { meterId } = await createMeter(page);
    return { meterId, documentId: await uploadPdf(page, meterId) };
  })();
  return source;
}
