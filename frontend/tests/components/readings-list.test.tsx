/** The readings list and voiding (spec 0011 child 0001 AC-9, AC-10). */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ReadingsList } from "@/components/readings/ReadingsList";
import { getStoredConsumptionQueryKey } from "@/lib/api/generated/default/default";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-00000000000a";
const READINGS = `*/api/v1/meters/${METER}/readings`;
const ZONE = "America/New_York";

function row(id: string, value: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    meter_id: METER,
    cumulative_kwh: value,
    recorded_at: "2026-11-01T16:00:00Z",
    original_local_date: "2026-11-01",
    source: "manual",
    status: "valid",
    created_at: "",
    status_changed_at: null,
    ...extra,
  };
}

function serve(items: ReturnType<typeof row>[], next: string | null = null) {
  server.use(http.get(READINGS, () => HttpResponse.json({ items, next_cursor: next })));
}

function renderList() {
  return renderWithClient(<ReadingsList meterId={METER} zone={ZONE} />);
}

describe("the rows", () => {
  it("asks for newest first, 50 per page", async () => {
    let params: URLSearchParams | null = null;
    server.use(
      http.get(READINGS, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    renderList();
    await screen.findByText(en.readings.emptyTitle);
    expect(params!.get("order")).toBe("desc");
    expect(params!.get("limit")).toBe("50");
  });

  it("shows a date only reading on its own day, never rounded", async () => {
    serve([row("a", "13049.123456", { original_local_date: "2026-11-01" })]);
    renderList();
    const item = await screen.findByRole("listitem");
    expect(item).toHaveTextContent("Nov 1, 2026");
    expect(item).toHaveTextContent("13,049.123456 kWh");
  });

  it("shows a timed reading in the property's zone", async () => {
    serve([row("a", "1", { original_local_date: null, recorded_at: "2026-11-05T02:30:00Z" })]);
    renderList();
    expect(await screen.findByRole("listitem")).toHaveTextContent("Nov 4, 2026, 9:30 PM");
  });

  it("marks voided rows in text and strikes them, with no Void action", async () => {
    serve([row("a", "100", { status: "voided" }), row("b", "90", { status: "flagged" })]);
    renderList();
    const [voided, flagged] = await screen.findAllByRole("listitem");
    expect(voided).toHaveTextContent(en.readings.voided);
    expect(within(voided).getByText("100 kWh")).toHaveClass("line-through");
    expect(within(voided).queryByRole("button")).toBeNull();
    expect(flagged).toHaveTextContent(en.readings.flagged);
    expect(within(flagged).getByRole("button", { name: /^Void/ })).toBeInTheDocument();
  });

  it("says Not available for an unreadable value instead of crashing", async () => {
    serve([row("a", "garbage")]);
    renderList();
    expect(await screen.findByRole("listitem")).toHaveTextContent(en.readings.notAvailable);
  });

  it("loads more and keeps rows when that fails", async () => {
    let fail = true;
    server.use(
      http.get(READINGS, ({ request }) => {
        if (new URL(request.url).searchParams.get("cursor") === null) {
          return HttpResponse.json({ items: [row("a", "2")], next_cursor: "more" });
        }
        return fail
          ? problem(500, "internal_error")
          : HttpResponse.json({ items: [row("b", "1")], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderList();
    await user.click(await screen.findByRole("button", { name: en.lists.loadMore }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    fail = false;
    await user.click(screen.getByRole("button", { name: en.lists.retry }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  });

  it("shows a failed first page with Retry, clean under axe", async () => {
    server.use(http.get(READINGS, () => problem(500, "internal_error")));
    const { container } = renderList();
    expect(await screen.findByRole("button", { name: en.lists.retry })).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is clean under axe while loading", async () => {
    server.use(http.get(READINGS, () => new Promise(() => undefined)));
    const { container } = renderList();
    expect(screen.getByRole("status", { name: en.lists.loading })).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("voiding", () => {
  async function openVoid(name: RegExp) {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name }));
    return { user, dialog: await screen.findByRole("alertdialog") };
  }

  it("names the value and date, and Cancel changes nothing", async () => {
    let patched = 0;
    serve([row("a", "13040")]);
    server.use(
      http.patch(`${READINGS}/a`, () => {
        patched += 1;
        return HttpResponse.json(row("a", "13040", { status: "voided" }));
      }),
    );
    renderList();
    const opener = await screen.findByRole("button", { name: /^Void 13,040 kWh/ });
    const { user, dialog } = await openVoid(/^Void 13,040 kWh/);
    expect(dialog).toHaveTextContent("13,040 kWh on November 1, 2026");
    await user.click(within(dialog).getByRole("button", { name: en.readings.voidCancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(patched).toBe(0);
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it.each([
    ["a fresh void", () => HttpResponse.json(row("a", "2", { status: "voided" }))],
    ["a repeat void answering 200", () => HttpResponse.json(row("a", "2", { status: "voided" }))],
  ])("%s closes, announces, refreshes, and focuses the next action", async (_name, answer) => {
    let body: unknown;
    let voided = false;
    server.use(
      http.get(READINGS, () =>
        HttpResponse.json({
          items: [row("a", "2", voided ? { status: "voided" } : {}), row("b", "1")],
          next_cursor: null,
        }),
      ),
      http.patch(`${READINGS}/a`, async ({ request }) => {
        body = await request.json();
        voided = true;
        return answer();
      }),
    );
    const { client } = renderList();
    const key = getStoredConsumptionQueryKey(METER, { from: "x", to: "y" });
    client.setQueryData(key, { ok: true });
    const { user, dialog } = await openVoid(/^Void 2 kWh/);
    await user.click(within(dialog).getByRole("button", { name: en.readings.voidConfirm }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(body).toEqual({ status: "voided" });
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    await waitFor(() => expect(screen.getByRole("button", { name: /^Void 1 kWh/ })).toHaveFocus());
    expect(document.querySelector("[role=status].sr-only")).toHaveTextContent(
      en.readings.voided_announcement("2", "November 1, 2026"),
    );
    await waitFor(() => expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Voided"));
  });

  it("focuses the list heading when no action is left", async () => {
    serve([row("a", "2")]);
    server.use(
      http.patch(`${READINGS}/a`, () => HttpResponse.json(row("a", "2", { status: "voided" }))),
    );
    renderList();
    const { user, dialog } = await openVoid(/^Void 2 kWh/);
    await user.click(within(dialog).getByRole("button", { name: en.readings.voidConfirm }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: en.readings.title })).toHaveFocus(),
    );
  });

  it("shows a failure inside the dialog, which stays open and can retry", async () => {
    let fail = true;
    serve([row("a", "2")]);
    server.use(
      http.patch(`${READINGS}/a`, () =>
        fail
          ? problem(500, "internal_error")
          : HttpResponse.json(row("a", "2", { status: "voided" })),
      ),
    );
    renderList();
    const { user, dialog } = await openVoid(/^Void 2 kWh/);
    const confirm = within(dialog).getByRole("button", { name: en.readings.voidConfirm });
    await user.click(confirm);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("req-123");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    fail = false;
    await user.click(confirm);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });
});
