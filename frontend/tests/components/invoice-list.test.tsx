/** The paged invoice list (spec 0012/0005 AC-1). */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { InvoiceListScreen } from "@/components/invoices/InvoiceListScreen";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-00000000000a";

function meter() {
  server.use(
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

function item(id: string, start: string) {
  return {
    id,
    meter_id: METER,
    created_at: "2026-11-04T17:00:00Z",
    current_revision_id: null,
    revisions: [
      {
        id: `${id}-r`,
        revision_number: 1,
        status: "draft",
        actor_id: "u",
        created_at: "2026-11-04T17:00:00Z",
        confirmed_at: null,
        distributor: "EDESUR",
        period_start: start,
        period_end: "2026-09-30",
        billed_kwh: "250.000000",
        total_dop: "100.00",
        energy_charge_dop: null,
        issue_date: null,
        due_date: null,
        field_origins: {},
        source_document_id: null,
        previous_revision_id: null,
        changed_fields: [],
        old_values: {},
      },
    ],
  };
}

describe("invoice list", () => {
  it("shows the empty state with the manual entry action", async () => {
    meter();
    server.use(
      http.get(`*/api/v1/meters/${METER}/invoices`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );
    renderWithClient(<InvoiceListScreen meterId={METER} zone="America/Santo_Domingo" />);
    expect(await screen.findByText(/no invoices have been saved/i)).toBeTruthy();
    expect(
      (await screen.findByRole("link", { name: /enter an invoice by hand/i })).getAttribute("href"),
    ).toBe(`/meters/${METER}/invoices/new`);
  });

  it("pages with a cursor and links each row to its review", async () => {
    meter();
    server.use(
      http.get(`*/api/v1/meters/${METER}/invoices`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return cursor
          ? HttpResponse.json({ items: [item("i2", "2026-08-01")], next_cursor: null })
          : HttpResponse.json({ items: [item("i1", "2026-09-01")], next_cursor: "c2" });
      }),
    );
    renderWithClient(<InvoiceListScreen meterId={METER} zone="America/Santo_Domingo" />);
    const first = await screen.findByRole("link", { name: /review.*2026-09-01/i });
    expect(first.getAttribute("href")).toBe("/invoices/i1");
    await userEvent.click(screen.getByRole("button", { name: /load more invoices/i }));
    expect(await screen.findByRole("link", { name: /review.*2026-08-01/i })).toBeTruthy();
  });

  it("offers retry after an error", async () => {
    meter();
    let calls = 0;
    server.use(
      http.get(`*/api/v1/meters/${METER}/invoices`, () => {
        calls += 1;
        return calls === 1
          ? problem(500, "internal_error")
          : HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    renderWithClient(<InvoiceListScreen meterId={METER} zone="America/Santo_Domingo" />);
    await userEvent.click(await screen.findByRole("button", { name: /^retry$/i }));
    expect(await screen.findByText(/no invoices have been saved/i)).toBeTruthy();
  });
});
