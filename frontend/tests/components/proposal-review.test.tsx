/** Proposal review (spec 0012/0005 AC-2, AC-3): evidence beside each value, draft only. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ProposalReview } from "@/components/documents/ProposalReview";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-0000000000b1";
const DOC = "00000000-0000-4000-8000-0000000000d1";
const RUN = "00000000-0000-4000-8000-0000000000e1";
const EXTRACTIONS = `*/api/v1/documents/${DOC}/extractions`;
const INVOICES = `*/api/v1/meters/${METER}/invoices`;

function field(name: string, extra: Record<string, unknown> = {}) {
  return {
    name,
    state: "not_found",
    value: null,
    quote: null,
    page_number: null,
    uncertainty: null,
    issues: [] as string[],
    evidence_verified: false,
    ...extra,
  };
}

function found(name: string, value: string, quote: string, extra: Record<string, unknown> = {}) {
  return field(name, {
    state: "explicit",
    value,
    quote,
    page_number: 1,
    evidence_verified: true,
    ...extra,
  });
}

type Contradiction = {
  field: string;
  candidates: Record<string, unknown>[];
};

function extraction(
  overrides: Record<string, Record<string, unknown>> = {},
  conflicts: { code: string; fields: string[] }[] = [],
  contradictions: Contradiction[] = [],
) {
  const fields = [
    found("distributor", "EDESUR", "EDESUR Dominicana"),
    found("tariff_class", "BTS-1", "Tarifa BTS-1"),
    found("period_start", "2026-09-01", "Desde: 01/09/2026"),
    found("period_end", "2026-09-30", "Hasta: 30/09/2026"),
    found("billed_kwh", "250", "Consumo facturado: 250 kWh"),
    found("total_dop", "3456.78", "Total a pagar: RD$ 3,456.78"),
    field("energy_charge_dop"),
    field("issue_date"),
    field("due_date"),
  ].map((item) => ({ ...item, ...overrides[item.name] }));
  return {
    items: [
      {
        run_id: RUN,
        run_number: 1,
        model: "fake-model",
        prompt_version: "pr1",
        finished_at: "2026-11-05T15:00:00Z",
        proposal: { fields, contradictions, conflicts, requires_review: true },
      },
    ],
    next_cursor: null,
  };
}

function renderReview(distributor: "EDESUR" | "EDEESTE" = "EDESUR") {
  return renderWithClient(
    <ProposalReview documentId={DOC} meterId={METER} distributor={distributor} />,
  );
}

describe("ProposalReview", () => {
  it("shows each value with its page, quote, and state, and has no axe violations", async () => {
    server.use(http.get(EXTRACTIONS, () => HttpResponse.json(extraction())));
    const { container } = renderReview();

    expect(await screen.findByText(/Total a pagar: RD\$ 3,456.78/)).toBeTruthy();
    expect(screen.getAllByText(/Page 1/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText(en.review.edited("Invoice total (DOP)"))).toHaveProperty(
      "value",
      "3456.78",
    );
    expect(screen.getByText(en.review.distributorSame("EDESUR"))).toBeTruthy();
    expect(screen.getByText(en.review.tariffClass("BTS-1"))).toBeTruthy();
    // A field the model did not find starts blank and says so.
    const charge = screen.getByLabelText(en.review.edited("Energy charge (DOP)"));
    expect(charge).toHaveProperty("value", "");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("saves a draft only, labels kept values as the document's and edited ones as manual", async () => {
    let sent: Record<string, unknown> | null = null;
    let headers: Headers | null = null;
    server.use(
      http.get(EXTRACTIONS, () => HttpResponse.json(extraction())),
      http.post(INVOICES, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        headers = request.headers;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    renderReview();
    const user = userEvent.setup();
    const total = await screen.findByLabelText(en.review.edited("Invoice total (DOP)"));
    await user.clear(total);
    await user.type(total, "3500.00");
    await user.type(screen.getByLabelText(en.review.edited("Due date")), "2026-10-15");
    await user.click(screen.getByRole("button", { name: en.review.save }));

    expect((await screen.findByRole("status")).textContent).toBe(en.review.saved);
    expect(sent).toMatchObject({
      source_document_id: DOC,
      distributor: "EDESUR",
      period_start: "2026-09-01",
      billed_kwh: "250",
      total_dop: "3500.00",
      energy_charge_dop: null,
      due_date: "2026-10-15",
      field_origins: {
        distributor: "document",
        period_start: "document",
        period_end: "document",
        billed_kwh: "document",
        total_dop: "manual",
        due_date: "manual",
      },
    });
    expect(headers!.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers!.get("X-EnergyIQ-CSRF")).toBe("1");
  });

  it("names the affected fields for a conflict and leaves a contradicted field blank", async () => {
    const candidate = (value: string, page: number) => ({
      value,
      raw_value: null,
      quote: `Total: RD$ ${value}`,
      page_number: page,
      evidence_verified: true,
      issues: [],
    });
    server.use(
      http.get(EXTRACTIONS, () =>
        HttpResponse.json(
          extraction(
            { total_dop: { issues: ["contradiction"], evidence_verified: false } },
            [
              { code: "period_inverted", fields: ["period_start", "period_end"] },
              { code: "contradiction", fields: ["total_dop"] },
            ],
            [{ field: "total_dop", candidates: [candidate("100.00", 1), candidate("200.00", 2)] }],
          ),
        ),
      ),
    );
    renderReview();

    const group = await screen.findByRole("group", { name: en.review.conflictsTitle });
    expect(
      within(group).getByText(en.review.conflict.period_inverted("Period start and Period end")),
    ).toBeTruthy();
    expect(
      within(group).getByText(en.review.conflict.contradiction("Invoice total (DOP)")),
    ).toBeTruthy();
    expect(screen.getByLabelText(en.review.edited("Invoice total (DOP)"))).toHaveProperty(
      "value",
      "",
    );
    expect(screen.getByText(/Total: RD\$ 200.00/)).toBeTruthy();
  });

  it("warns when the bill names another distributor and still uses the meter's", async () => {
    server.use(http.get(EXTRACTIONS, () => HttpResponse.json(extraction())));
    renderReview("EDEESTE");
    expect(await screen.findByText(en.review.distributorOther("EDESUR", "EDEESTE"))).toBeTruthy();
  });

  it("explains a refused save and keeps the edits", async () => {
    server.use(
      http.get(EXTRACTIONS, () => HttpResponse.json(extraction())),
      http.post(INVOICES, () => problem(422, "origin_mismatch")),
    );
    renderReview();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: en.review.save }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.review.saveMismatch);
    expect(screen.getByLabelText(en.review.edited("Invoice total (DOP)"))).toHaveProperty(
      "value",
      "3456.78",
    );
  });

  it("points to manual entry when the run left no proposal", async () => {
    server.use(http.get(EXTRACTIONS, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderReview();
    expect(await screen.findByText(en.review.nothing)).toBeTruthy();
    expect(screen.queryByRole("button", { name: en.review.save })).toBeNull();
  });

  it("offers retry when the proposal fails to load", async () => {
    let calls = 0;
    server.use(
      http.get(EXTRACTIONS, () => {
        calls += 1;
        return calls === 1 ? problem(503, "service_unavailable") : HttpResponse.json(extraction());
      }),
    );
    renderReview();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: en.review.retry }));
    expect(await screen.findByRole("button", { name: en.review.save })).toBeTruthy();
  });
});
