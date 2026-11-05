/** Editing an unconfirmed invoice draft in steps (spec 0012 child 0001 AC-1, AC-3). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { InvoicePanel } from "@/components/invoices/InvoicePanel";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-00000000000a";
const INVOICE = "00000000-0000-4000-8000-0000000000b1";
const REV1 = "00000000-0000-4000-8000-0000000000c1";
const REV2 = "00000000-0000-4000-8000-0000000000c2";

function revision(id: string, number: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    revision_number: number,
    status: "draft",
    actor_id: "u",
    created_at: "2026-11-04T17:00:00Z",
    confirmed_at: null,
    distributor: "EDESUR",
    period_start: null,
    period_end: null,
    billed_kwh: null,
    total_dop: "10.50",
    energy_charge_dop: null,
    issue_date: null,
    due_date: null,
    field_origins: { total_dop: "manual" },
    previous_revision_id: null,
    changed_fields: [],
    old_values: {},
    ...extra,
  };
}

function invoice(revisions: ReturnType<typeof revision>[]) {
  return {
    id: INVOICE,
    meter_id: METER,
    created_at: "2026-11-04T17:00:00Z",
    current_revision_id: null,
    revisions,
  };
}

function list(items: unknown[]) {
  server.use(
    http.get(`*/api/v1/meters/${METER}/invoices`, () =>
      HttpResponse.json({ items, next_cursor: null }),
    ),
  );
}

function renderPanel() {
  return renderWithClient(
    <InvoicePanel meterId={METER} distributor="EDESUR" zone="America/Santo_Domingo" />,
  );
}

describe("completing a partial draft", () => {
  it("sends only the changed fields with the revision it was opened on", async () => {
    list([invoice([revision(REV1, 1)])]);
    const posts: Record<string, unknown>[] = [];
    server.use(
      http.post(`*/api/v1/invoices/${INVOICE}/revisions`, async ({ request }) => {
        posts.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          invoice([
            revision(REV1, 1),
            revision(REV2, 2, { period_start: "2026-10-01", previous_revision_id: REV1 }),
          ]),
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Edit draft" }));
    expect(screen.getByRole("heading", { name: "Edit draft" })).toBeInTheDocument();
    await user.type(screen.getAllByLabelText("Period start")[1], "2026-10-01");
    await user.click(screen.getByRole("button", { name: "Save draft changes" }));
    expect(await screen.findByText(/Draft updated/)).toBeInTheDocument();
    expect(posts).toEqual([
      { base_revision_id: REV1, expected_current_revision_id: null, period_start: "2026-10-01" },
    ]);
  });

  it("asks for a change before sending anything", async () => {
    list([invoice([revision(REV1, 1)])]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Edit draft" }));
    await user.click(screen.getByRole("button", { name: "Save draft changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Change at least one value before saving.",
    );
  });

  it("explains a stale revision, reloads, and the next save uses the newest base", async () => {
    let reads = 0;
    const posts: Record<string, unknown>[] = [];
    server.use(
      http.get(`*/api/v1/meters/${METER}/invoices`, () => {
        reads += 1;
        const revisions =
          reads === 1
            ? [revision(REV1, 1)]
            : [revision(REV1, 1), revision(REV2, 2, { total_dop: "11.00" })];
        return HttpResponse.json({ items: [invoice(revisions)], next_cursor: null });
      }),
      http.post(`*/api/v1/invoices/${INVOICE}/revisions`, async ({ request }) => {
        posts.push((await request.json()) as Record<string, unknown>);
        if (posts.length === 1) return problem(409, "stale_invoice_revision");
        return HttpResponse.json(invoice([revision(REV1, 1), revision(REV2, 2)]), {
          status: 201,
        });
      }),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Edit draft" }));
    await user.type(screen.getAllByLabelText("Period end")[1], "2026-10-31");
    await user.click(screen.getByRole("button", { name: "Save draft changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed since you opened it/);
    await waitFor(() =>
      expect(screen.getAllByLabelText("Invoice total (DOP)")[1]).toHaveValue("11.00"),
    );
    await user.type(screen.getAllByLabelText("Period end")[1], "2026-10-31");
    await user.click(screen.getByRole("button", { name: "Save draft changes" }));
    expect(await screen.findByText(/Draft updated/)).toBeInTheDocument();
    expect(posts[1]).toEqual({
      base_revision_id: REV2,
      expected_current_revision_id: null,
      period_end: "2026-10-31",
    });
  });

  it("labels history by what each revision is now", async () => {
    const confirmed = revision(REV2, 2, { status: "confirmed", period_start: "2026-10-01" });
    list([{ ...invoice([revision(REV1, 1), confirmed]), current_revision_id: REV2 }]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByText("Revision history"));
    expect(screen.getByText(/Revision 1, superseded draft/)).toBeInTheDocument();
    expect(screen.getByText(/Revision 2, current/)).toBeInTheDocument();
  });

  it("saves a new draft with values missing", async () => {
    list([]);
    const posts: Record<string, unknown>[] = [];
    server.use(
      http.post(`*/api/v1/meters/${METER}/invoices`, async ({ request }) => {
        posts.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(invoice([revision(REV1, 1)]), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.type(await screen.findByLabelText("Invoice total (DOP)"), "10.50");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(/Draft saved/)).toBeInTheDocument();
    expect(posts[0]).toMatchObject({
      distributor: "EDESUR",
      total_dop: "10.50",
      period_start: null,
    });
  });

  it("treats an equal number in another format as no change", async () => {
    list([invoice([revision(REV1, 1, { billed_kwh: "100.000000" })])]);
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Edit draft" }));
    const field = screen.getAllByLabelText("Billed use (kWh)")[1];
    await user.clear(field);
    await user.type(field, "100");
    await user.click(screen.getByRole("button", { name: "Save draft changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Change at least one value before saving.",
    );
  });

  it("is read only for an inactive meter", async () => {
    list([invoice([revision(REV1, 1)])]);
    renderWithClient(
      <InvoicePanel
        meterId={METER}
        distributor="EDESUR"
        zone="America/Santo_Domingo"
        active={false}
      />,
    );
    expect(await screen.findByText(/This meter is inactive/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit draft" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm revision" })).toBeNull();
  });
});
