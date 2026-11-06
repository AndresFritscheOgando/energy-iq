/** The invoice review screen (spec 0012/0005 AC-2 to AC-4). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { InvoiceReview, confirmProblems } from "@/components/invoices/InvoiceReview";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-00000000000a";
const INVOICE = "00000000-0000-4000-8000-0000000000b1";
const DOC = "00000000-0000-4000-8000-0000000000d1";
const REV1 = "00000000-0000-4000-8000-0000000000c1";
const REV2 = "00000000-0000-4000-8000-0000000000c2";
const ZONE = "America/Santo_Domingo";

function revision(id: string, number: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    revision_number: number,
    status: "draft",
    actor_id: "u",
    created_at: "2026-11-04T17:00:00Z",
    confirmed_at: null,
    distributor: "EDESUR",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    billed_kwh: "250.000000",
    total_dop: "3456.78",
    energy_charge_dop: null,
    issue_date: null,
    due_date: null,
    field_origins: {
      period_start: "manual",
      period_end: "manual",
      billed_kwh: "manual",
      total_dop: "manual",
    },
    source_document_id: null,
    previous_revision_id: null,
    changed_fields: [],
    old_values: {},
    ...extra,
  };
}

function invoice(revisions: ReturnType<typeof revision>[], current: string | null = null) {
  return {
    id: INVOICE,
    meter_id: METER,
    created_at: "2026-11-04T17:00:00Z",
    current_revision_id: current,
    revisions,
  };
}

function serve(body: ReturnType<typeof invoice>) {
  server.use(
    http.get(`*/api/v1/invoices/${INVOICE}`, () => HttpResponse.json(body)),
    http.get(`*/api/v1/meters/${METER}`, () =>
      HttpResponse.json({
        id: METER,
        property_id: "p",
        label: "Main",
        distributor: "EDESUR",
        active: true,
        created_at: "2026-11-01T00:00:00Z",
      }),
    ),
  );
}

describe("review values and sources", () => {
  it("labels fields entered by hand as having no source document", async () => {
    serve(invoice([revision(REV1, 1)]));
    renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    expect(
      await screen.findByText(/entered by hand, so there is no source document/i),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: /download/i })).toBeNull();
    expect(screen.getAllByText("Entered or changed by you").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No source evidence").length).toBeGreaterThan(0);
  });

  it("shows page evidence and a download link, never an embedded PDF", async () => {
    serve(
      invoice([
        revision(REV1, 1, {
          source_document_id: DOC,
          field_origins: { total_dop: "document" },
        }),
      ]),
    );
    server.use(
      http.get(`*/api/v1/documents/${DOC}`, () =>
        HttpResponse.json({ id: DOC, state: "needs_review" }),
      ),
      http.get(`*/api/v1/documents/${DOC}/extractions`, () =>
        HttpResponse.json({
          items: [
            {
              run_id: "r",
              run_number: 1,
              model: "m",
              prompt_version: "p",
              finished_at: "2026-11-05T15:00:00Z",
              proposal: {
                fields: [
                  {
                    name: "total_dop",
                    state: "explicit",
                    value: "3456.78",
                    quote: "Total a pagar: RD$ 3,456.78",
                    page_number: 2,
                    uncertainty: null,
                    issues: [],
                    evidence_verified: true,
                  },
                ],
                contradictions: [],
                conflicts: [],
                requires_review: true,
              },
            },
          ],
          next_cursor: null,
        }),
      ),
    );
    const { container } = renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    const link = await screen.findByRole("link", { name: /download the original pdf/i });
    expect(link.getAttribute("href")).toBe(`/api/v1/documents/${DOC}/source`);
    expect(link.hasAttribute("download")).toBe(true);
    expect(await screen.findByText(/Total a pagar: RD\$ 3,456.78/)).toBeTruthy();
    expect(screen.getByText(/Page 2/)).toBeTruthy();
    expect(container.querySelector("iframe, embed, object")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("conflicts and contradictions", () => {
  it("names the affected fields and lists each competing value without choosing one", async () => {
    serve(invoice([revision(REV1, 1, { source_document_id: DOC })]));
    const field = (name: string, extra: Record<string, unknown> = {}) => ({
      name,
      state: "not_found",
      value: null,
      quote: null,
      page_number: null,
      uncertainty: null,
      issues: [] as string[],
      evidence_verified: false,
      ...extra,
    });
    server.use(
      http.get(`*/api/v1/documents/${DOC}`, () =>
        HttpResponse.json({ id: DOC, state: "needs_review" }),
      ),
      http.get(`*/api/v1/documents/${DOC}/extractions`, () =>
        HttpResponse.json({
          items: [
            {
              run_id: "r",
              run_number: 1,
              model: "m",
              prompt_version: "p",
              finished_at: "2026-11-05T15:00:00Z",
              proposal: {
                fields: [
                  field("billed_kwh", { issues: ["contradiction"] }),
                  field("period_start", {
                    state: "explicit",
                    value: "2026-10-05",
                    quote: "Desde: 05/10/2026",
                    page_number: 1,
                    evidence_verified: true,
                  }),
                ],
                contradictions: [
                  {
                    field: "billed_kwh",
                    candidates: [
                      { value: "250", raw_value: "250", quote: "Consumo: 250 kWh", page_number: 1 },
                      { value: "260", raw_value: "260", quote: "Total kWh: 260", page_number: 2 },
                    ],
                  },
                ],
                conflicts: [
                  { code: "period_inverted", fields: ["period_start", "period_end"] },
                  { code: "contradiction", fields: ["billed_kwh"] },
                ],
                requires_review: true,
              },
            },
          ],
          next_cursor: null,
        }),
      ),
    );
    const { container } = renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    const group = await screen.findByRole("group", { name: /needs your attention/i });
    expect(group.textContent).toContain(
      "Period start and Period end: the period starts after it ends.",
    );
    expect(group.textContent).toContain("Billed use (kWh): the bill shows more than one value.");
    expect(screen.getByText(/Consumo: 250 kWh/)).toBeTruthy();
    expect(screen.getByText(/Total kWh: 260/)).toBeTruthy();
    expect(screen.getByText(/more than one value, so none is filled in/i)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("confirming", () => {
  it("names each missing field and sends nothing", async () => {
    serve(
      invoice([
        revision(REV1, 1, {
          billed_kwh: null,
          period_end: null,
          field_origins: { period_start: "manual", total_dop: "manual" },
        }),
      ]),
    );
    let posted = false;
    server.use(
      http.post(`*/api/v1/invoices/${INVOICE}/confirm`, () => {
        posted = true;
        return HttpResponse.json(invoice([revision(REV1, 1)]));
      }),
    );
    renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    await userEvent.click(await screen.findByRole("button", { name: /confirm this revision/i }));
    const heading = await screen.findByText(/these values stop confirmation/i);
    const box = heading.closest("div")!;
    expect(box.textContent).toContain("Period end is missing");
    expect(box.textContent).toContain("Billed use (kWh) is missing");
    expect(posted).toBe(false);
  });

  it("asks to save edits before confirming", async () => {
    serve(invoice([revision(REV1, 1)]));
    renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    const total = await screen.findByLabelText(/invoice total/i);
    await userEvent.clear(total);
    await userEvent.type(total, "99.00");
    await userEvent.click(screen.getByRole("button", { name: /confirm this revision/i }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/unsaved edits/i);
  });

  it("sends the draft revision and the expected current revision", async () => {
    serve(invoice([revision(REV1, 1)]));
    const sent: unknown[] = [];
    server.use(
      http.post(`*/api/v1/invoices/${INVOICE}/confirm`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(
          invoice(
            [revision(REV1, 1, { status: "confirmed", confirmed_at: "2026-11-06T10:00:00Z" })],
            REV1,
          ),
        );
      }),
    );
    renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    await userEvent.click(await screen.findByRole("button", { name: /confirm this revision/i }));
    expect(await screen.findByText("Invoice confirmed.")).toBeTruthy();
    expect(sent).toEqual([{ draft_revision_id: REV1, expected_current_revision_id: null }]);
  });

  it("keeps edits visible on a stale answer and lets the owner choose", async () => {
    serve(invoice([revision(REV1, 1)]));
    const bodies: unknown[] = [];
    server.use(
      http.post(`*/api/v1/invoices/${INVOICE}/revisions`, async ({ request }) => {
        bodies.push(await request.json());
        return problem(409, "stale_invoice_revision");
      }),
    );
    renderWithClient(<InvoiceReview invoiceId={INVOICE} zone={ZONE} />);
    const total = await screen.findByLabelText(/invoice total/i);
    await userEvent.clear(total);
    await userEvent.type(total, "99.00");
    await userEvent.click(screen.getByRole("button", { name: /save draft changes/i }));
    expect(await screen.findByText(/your edits are still in the form/i)).toBeTruthy();
    expect((screen.getByLabelText(/invoice total/i) as HTMLInputElement).value).toBe("99.00");
    // Saving is blocked, so nothing retries a different revision on its own.
    expect(
      (screen.getByRole("button", { name: /save draft changes/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(bodies).toHaveLength(1);

    server.use(
      http.get(`*/api/v1/invoices/${INVOICE}`, () =>
        HttpResponse.json(
          invoice([
            revision(REV1, 1),
            revision(REV2, 2, { total_dop: "50.00", billed_kwh: "260.000000" }),
          ]),
        ),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /keep my edits/i }));
    await waitFor(() => expect(screen.queryByText(/your edits are still in the form/i)).toBeNull());
    expect((screen.getByLabelText(/invoice total/i) as HTMLInputElement).value).toBe("99.00");
    // Fields the owner did not touch take the newer saved value, not the stale copy.
    expect((screen.getByLabelText(/billed use/i) as HTMLInputElement).value).toBe("260.000000");
  });
});

describe("confirmProblems", () => {
  it("reports a distributor that differs from the meter and an inverted period", () => {
    const row = revision(REV1, 1, { period_start: "2026-10-01", distributor: "EDENORTE" });
    const found = confirmProblems(row as never, "EDESUR");
    expect(found.some((text) => text.includes("differs from this meter"))).toBe(true);
    expect(found).toContain("Period start is after period end");
  });
});
