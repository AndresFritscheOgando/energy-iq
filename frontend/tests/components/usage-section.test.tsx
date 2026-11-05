/**
 * The usage view's states, tiles, table, readout, and server rendering (spec
 * 0011 child 0002 AC-2, AC-5 to AC-11). Recharts can't lay out in jsdom, so the
 * drawing is checked in a real browser and replaced with a stub here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { UsageSection } from "@/components/consumption/UsageSection";
import * as fetcher from "@/lib/api/fetcher";
import { getStoredConsumptionQueryKey } from "@/lib/api/generated/default/default";
import type { GapOut, IntervalOut } from "@/lib/api/generated/model";
import type { Range } from "@/lib/zoned-time";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

vi.mock("next/dynamic", () => ({ default: () => () => <div data-testid="chart-stub" /> }));

const METER = "00000000-0000-4000-8000-00000000000a";
const URL_ = `*/api/v1/meters/${METER}/consumption`;
const WINDOW = { from: "2026-10-01T04:00:00Z", to: "2026-11-01T04:00:00Z" };
const ZONE = "America/Santo_Domingo";

function interval(start: string, end: string, rate: string, kwh: string, duration: string) {
  return {
    start,
    end,
    kwh_per_day: rate,
    consumption_kwh: kwh,
    duration,
    event_ids: [],
    measured_in_window: true,
    previous_reading_id: "p",
    current_reading_id: "c",
    reason: null,
    status: "valid",
  } satisfies IntervalOut;
}

function gap(start: string, end: string, reason: GapOut["reason"], duration: string): GapOut {
  return {
    start,
    end,
    reason,
    duration,
    interval_reason: null,
    event_ids: [],
    previous_reading_id: null,
    current_reading_id: null,
  };
}

function summary(extra: Record<string, unknown> = {}) {
  return {
    measured_kwh: "28.000000",
    average_kwh_per_day: "4.000000",
    coverage_ratio: "0.2258",
    covered: "P7D",
    uncovered: "P24D",
    intervals: [
      interval("2026-10-05T16:00:00Z", "2026-10-12T16:00:00Z", "4.000000", "28.000000", "P7D"),
    ],
    gaps: [
      gap("2026-10-01T04:00:00Z", "2026-10-05T16:00:00Z", "before_first_reading", "P4DT12H"),
      gap("2026-10-12T16:00:00Z", "2026-11-01T04:00:00Z", "after_last_reading", "P19DT12H"),
    ],
    window: { start: WINDOW.from, end: WINDOW.to },
    ...extra,
  };
}

function section(range: Range = "30d", canAddReadings = true) {
  return (
    <UsageSection
      meterId={METER}
      zone={ZONE}
      range={range}
      window={WINDOW}
      canAddReadings={canAddReadings}
    />
  );
}

function serve(body: object) {
  server.use(http.get(URL_, () => HttpResponse.json(body)));
}

describe("the query", () => {
  it("uses the window prop as the key, never recomputing it", async () => {
    let params: URLSearchParams | null = null;
    server.use(
      http.get(URL_, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json(summary());
      }),
    );
    const { client } = renderWithClient(section());
    await screen.findByTestId("chart-stub");
    expect(params!.get("from")).toBe(WINDOW.from);
    expect(params!.get("to")).toBe(WINDOW.to);
    expect(client.getQueryData(getStoredConsumptionQueryKey(METER, WINDOW))).toBeDefined();
  });
});

describe("range links", () => {
  it("are links with aria-current on the active one", async () => {
    serve(summary());
    renderWithClient(section("90d"));
    const nav = await screen.findByRole("navigation", { name: en.usage.rangeLabel });
    const active = within(nav).getByRole("link", { name: "90 days" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active).toHaveAttribute("href", `/meters/${METER}?range=90d`);
    expect(within(nav).getByRole("link", { name: "30 days" })).not.toHaveAttribute("aria-current");
  });
});

describe("tiles", () => {
  it("show exact values at two places", async () => {
    serve(
      summary({
        measured_kwh: "1234.565000",
        average_kwh_per_day: "13.715000",
        coverage_ratio: "0.8450",
      }),
    );
    renderWithClient(section());
    expect(await screen.findByText("1,234.56")).toBeInTheDocument();
    expect(screen.getByText("13.72")).toBeInTheDocument();
    expect(screen.getAllByText("84%").length).toBeGreaterThan(0);
  });

  it("say Not available for a null average, and zero stays a real value", async () => {
    serve(
      summary({
        measured_kwh: "0",
        average_kwh_per_day: null,
        coverage_ratio: "0.0000",
        covered: "PT0S",
        intervals: [],
      }),
    );
    renderWithClient(section());
    expect(await screen.findByText("0.00")).toBeInTheDocument();
    expect(screen.getByText(en.usage.notAvailable)).toBeInTheDocument();
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
  });

  it("never say 100% with gaps or 0% with something measured", async () => {
    serve(summary({ coverage_ratio: "0.9990" }));
    const first = renderWithClient(section());
    expect((await screen.findAllByText("over 99%")).length).toBeGreaterThan(0);
    first.unmount();

    serve(summary({ coverage_ratio: "0.0010" }));
    renderWithClient(section());
    expect((await screen.findAllByText("under 1%")).length).toBeGreaterThan(0);
  });
});

describe("states", () => {
  it("loading has a polite status and reserved skeletons, clean under axe", async () => {
    server.use(http.get(URL_, () => new Promise(() => undefined)));
    const { container } = renderWithClient(section());
    expect(screen.getByRole("status")).toHaveTextContent(en.usage.loading);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBe(2);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("an error with no data has its reference and Retry, which recovers", async () => {
    let fail = true;
    server.use(
      http.get(URL_, () => (fail ? problem(500, "internal_error") : HttpResponse.json(summary()))),
    );
    const { container } = renderWithClient(section());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.usage.errorTitle);
    expect(alert).toHaveTextContent("req-123");
    expect(await axeViolations(container)).toEqual([]);

    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: en.usage.retry }));
    expect(await screen.findByTestId("chart-stub")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("an outage uses the unavailable copy", async () => {
    server.use(http.get(URL_, () => problem(503, "database_unavailable")));
    renderWithClient(section());
    expect(await screen.findByText(en.unavailable.message)).toBeInTheDocument();
  });

  it("couldn't refresh keeps the old data, marked out of date, and Retry recovers", async () => {
    let fail = false;
    server.use(
      http.get(URL_, () => (fail ? problem(500, "internal_error") : HttpResponse.json(summary()))),
    );
    const { client, container } = renderWithClient(section());
    await screen.findByTestId("chart-stub");

    fail = true;
    void client.invalidateQueries({ queryKey: getStoredConsumptionQueryKey(METER) });
    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(en.usage.staleTitle);
    expect(notice).toHaveTextContent("req-123");
    expect(screen.getByText(/^As of /)).toBeInTheDocument();
    expect(screen.getAllByText("28.00")[0]).toHaveClass("text-muted-foreground");
    expect(screen.getByTestId("chart-stub")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    fail = false;
    await userEvent.setup().click(within(notice).getByRole("button", { name: en.usage.retry }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByText(/^As of /)).toBeNull();
  });

  it("keeps old data visible while a refetch runs", async () => {
    let release: (value: Response) => void = () => undefined;
    let held = false;
    server.use(
      http.get(URL_, () =>
        held ? new Promise((resolve) => (release = resolve)) : HttpResponse.json(summary()),
      ),
    );
    const { client } = renderWithClient(section());
    await screen.findByTestId("chart-stub");
    held = true;
    void client.invalidateQueries({ queryKey: getStoredConsumptionQueryKey(METER) });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.getAllByText("28.00").length).toBeGreaterThan(0);
    expect(screen.queryByText(en.usage.loading)).toBeNull();
    release(HttpResponse.json(summary({ measured_kwh: "30.000000" })));
    expect((await screen.findAllByText("30.00")).length).toBeGreaterThan(0);
  });

  it("needs readings has no empty axes and points at the form", async () => {
    serve(
      summary({
        measured_kwh: "0",
        average_kwh_per_day: null,
        coverage_ratio: "0.0000",
        intervals: [],
        gaps: [gap(WINDOW.from, WINDOW.to, "no_intervals", "P31D")],
      }),
    );
    renderWithClient(section());
    expect(await screen.findByText(en.usage.needsTitle)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.usage.needsLink })).toHaveAttribute(
      "href",
      "#reading-value",
    );
    expect(screen.queryByTestId("chart-stub")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("needs readings on an inactive meter doesn't point at a form that isn't there", async () => {
    serve(summary({ intervals: [], gaps: [gap(WINDOW.from, WINDOW.to, "no_intervals", "P31D")] }));
    renderWithClient(section("30d", false));
    await screen.findByText(en.usage.needsTitle);
    expect(screen.queryByRole("link", { name: en.usage.needsLink })).toBeNull();
  });

  const nothing = () =>
    summary({
      measured_kwh: "0",
      average_kwh_per_day: null,
      coverage_ratio: "0.0000",
      covered: "PT0S",
      intervals: [],
      gaps: [gap(WINDOW.from, WINDOW.to, "after_last_reading", "P31D")],
    });

  it.each([
    ["30d", "90 days", "90d"],
    ["90d", "365 days", "365d"],
  ] as const)("nothing measured at %s links to %s", async (range, label, target) => {
    serve(nothing());
    renderWithClient(section(range));
    expect(
      await screen.findByText(en.usage.nothingTitle(en.usage.ranges[range])),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Show the last ${label}` })).toHaveAttribute(
      "href",
      `/meters/${METER}?range=${target}`,
    );
    expect(screen.getByTestId("chart-stub")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("nothing measured at 365 days suggests nothing", async () => {
    serve(nothing());
    renderWithClient(section("365d"));
    await screen.findByText(en.usage.nothingTitle("365 days"));
    expect(screen.queryByRole("link", { name: /Show the last/ })).toBeNull();
  });

  it("partial shows the calm note, not an alert", async () => {
    serve(summary({ coverage_ratio: "0.2258" }));
    renderWithClient(section());
    expect(await screen.findByText(en.usage.partial("23%"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("no gaps shows no notice", async () => {
    serve(summary({ gaps: [], coverage_ratio: "1.0000", covered: "P31D" }));
    renderWithClient(section());
    expect((await screen.findAllByText("100%")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/never counted as zero/)).toBeNull();
  });
});

describe("the figure", () => {
  it("captions the range, values, gap count, and points to the table", async () => {
    serve(summary());
    renderWithClient(section());
    const caption = (await screen.findByRole("figure")).querySelector("figcaption");
    expect(caption).toHaveTextContent("last 30 days");
    expect(caption).toHaveTextContent("28.00 kWh");
    expect(caption).toHaveTextContent("4.00 kWh per day");
    expect(caption).toHaveTextContent("23%");
    expect(caption).toHaveTextContent("2 gaps");
    expect(caption).toHaveTextContent(/table/i);
  });

  it("is clean under axe with a table", async () => {
    serve(summary());
    const { container } = renderWithClient(section());
    await screen.findByRole("table");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("the readout", () => {
  const readout = () => screen.getByTestId("chart-readout");

  async function ready() {
    serve(summary());
    renderWithClient(section());
    return screen.findByTestId("usage-chart");
  }

  it("starts on the newest measured step, in a polite live region", async () => {
    await ready();
    expect(readout()).toHaveAttribute("aria-live", "polite");
    expect(readout()).toHaveTextContent(
      "Oct 5 to Oct 12: 4.00 kWh per day, 28.00 kWh, average over 7 days",
    );
  });

  it("moves with arrows in time order, and Home and End jump to the ends", async () => {
    const chart = await ready();
    expect(chart).toHaveAttribute("tabindex", "0");
    expect(chart).toHaveAccessibleName(en.usage.chartLabel);

    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(readout()).toHaveTextContent("No reading yet after this date.");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(readout()).toHaveTextContent("No reading yet after this date.");
    fireEvent.keyDown(chart, { key: "Home" });
    expect(readout()).toHaveTextContent("Before your first reading.");
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(readout()).toHaveTextContent("Before your first reading.");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(readout()).toHaveTextContent("4.00 kWh per day");
    fireEvent.keyDown(chart, { key: "End" });
    expect(readout()).toHaveTextContent("No reading yet after this date.");
  });

  it("highlights the selected table row", async () => {
    const chart = await ready();
    const row = () => screen.getByRole("table").querySelector('tr[data-kind="step"]');
    expect(row()).toHaveClass("bg-accent");
    fireEvent.keyDown(chart, { key: "Home" });
    expect(row()).not.toHaveClass("bg-accent");
  });

  it("selects the segment under the pointer from the fixed margins", async () => {
    const chart = await ready();
    vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
      left: 100,
      width: 1044,
      top: 0,
      right: 0,
      bottom: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    // Plot: y axis 36 wide, right margin 8, so 1000 px for 31 days.
    fireEvent.pointerMove(chart, { clientX: 100 + 36 + 50 });
    expect(readout()).toHaveTextContent("Before your first reading.");
    fireEvent.pointerMove(chart, { clientX: 100 + 36 + 900 });
    expect(readout()).toHaveTextContent("No reading yet after this date.");
    fireEvent.pointerMove(chart, { clientX: 100 + 36 + 250 });
    expect(readout()).toHaveTextContent("4.00 kWh per day");
    fireEvent.pointerMove(chart, { clientX: 5 });
    expect(readout()).toHaveTextContent("4.00 kWh per day");
  });
});

describe("the table", () => {
  it("merges steps and gaps newest first, and a gap shows no number", async () => {
    serve(summary());
    renderWithClient(section());
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("No measured usage");
    expect(rows[0]).toHaveTextContent("No reading yet after this date.");
    expect(rows[0]).not.toHaveTextContent("0.00");
    expect(rows[1]).toHaveTextContent("Oct 5, 2026");
    expect(rows[1]).toHaveTextContent("7 days");
    expect(rows[1]).toHaveTextContent("28.00");
    expect(rows[1]).toHaveTextContent("Average over 7 days");
    expect(rows[2]).toHaveTextContent("Before your first reading.");
  });

  it("scrolls in its own focusable region", async () => {
    serve(summary());
    renderWithClient(section());
    const region = await screen.findByRole("region", { name: en.usage.tableTitle });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveClass("overflow-x-auto");
  });
});

describe("server rendering", () => {
  it("renders loading with an empty client and never calls apiFetch", () => {
    const spy = vi.spyOn(fetcher, "apiFetch");
    const client = new QueryClient();
    const html = renderToString(
      <QueryClientProvider client={client}>{section()}</QueryClientProvider>,
    );
    expect(html).toContain(en.usage.loading);
    expect(spy).not.toHaveBeenCalled();
  });

  it("renders tiles and table when the prefetch succeeded", () => {
    const client = new QueryClient();
    client.setQueryData(getStoredConsumptionQueryKey(METER, WINDOW), summary());
    const html = renderToString(
      <QueryClientProvider client={client}>{section()}</QueryClientProvider>,
    );
    expect(html).toContain("28.00");
    expect(html).toContain(en.usage.tableTitle);
    expect(html).not.toContain(en.usage.loading);
  });
});
