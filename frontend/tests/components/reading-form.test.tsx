/**
 * The reading form, its lower value warning, and save results (spec 0011 child
 * 0001 AC-6 to AC-8, AC-11, AC-12).
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReadingForm } from "@/components/readings/ReadingForm";
import { MeterScreen } from "@/components/readings/MeterScreen";
import { getGetMeterQueryKey } from "@/lib/api/generated/meters/meters";
import { getStoredConsumptionQueryKey } from "@/lib/api/generated/default/default";
import { readingsListOptions } from "@/lib/api/list-queries";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const METER = "00000000-0000-4000-8000-00000000000a";
const READINGS = `*/api/v1/meters/${METER}/readings`;
const ZONE = "America/New_York";
const TODAY = "2026-11-04";
const WINDOW = { from: "2026-08-06T04:00:00Z", to: "2026-11-05T05:00:00Z" };

function reading(extra: Record<string, unknown> = {}) {
  return {
    id: "r-new",
    meter_id: METER,
    cumulative_kwh: "13049.000000",
    recorded_at: "2026-11-04T17:00:00Z",
    original_local_date: "2026-11-04",
    source: "manual",
    status: "valid",
    created_at: "",
    status_changed_at: null,
    ...extra,
  };
}

type Recorded = { lookups: URLSearchParams[]; posts: unknown[]; keys: (string | null)[] };

/** The lookup answers `earlier`; the POST answers `save` (default: success). */
function api({
  earlier = null,
  lookup,
  save,
}: {
  earlier?: Record<string, unknown> | null;
  lookup?: () => Response | Promise<Response>;
  save?: () => Response | Promise<Response>;
} = {}): Recorded {
  const recorded: Recorded = { lookups: [], posts: [], keys: [] };
  server.use(
    http.get(READINGS, ({ request }) => {
      recorded.lookups.push(new URL(request.url).searchParams);
      return lookup
        ? lookup()
        : HttpResponse.json({ items: earlier ? [earlier] : [], next_cursor: null });
    }),
    http.post(READINGS, async ({ request }) => {
      recorded.posts.push(await request.json());
      recorded.keys.push(request.headers.get("Idempotency-Key"));
      return save ? save() : HttpResponse.json(reading(), { status: 201 });
    }),
  );
  return recorded;
}

function renderForm(onInactive = vi.fn()) {
  const view = renderWithClient(
    <ReadingForm
      meterId={METER}
      zone={ZONE}
      today={TODAY}
      window={WINDOW}
      onInactive={onInactive}
    />,
  );
  return { ...view, onInactive };
}

const value = () => screen.getByLabelText(new RegExp(en.readingForm.value));
const date = () => screen.getByLabelText(en.readingForm.date);
const time = () => screen.getByLabelText(new RegExp(en.readingForm.time));

async function submit(text: string, user = userEvent.setup()) {
  await user.clear(value());
  await user.type(value(), text);
  await user.click(screen.getByRole("button", { name: en.readingForm.submit }));
  return user;
}

beforeEach(() => router.refresh.mockReset());

describe("the fields", () => {
  it("defaults to today from the server, and future dates can't be chosen", () => {
    renderForm();
    expect(date()).toHaveValue(TODAY);
    expect(date()).toHaveAttribute("max", TODAY);
    expect(value()).toHaveAttribute("inputmode", "decimal");
    expect(time()).toHaveValue("");
  });

  it("recomputes today when the date field gets focus", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-05T15:00:00Z") });
    renderForm();
    await userEvent.setup().click(date());
    expect(date()).toHaveAttribute("max", "2026-11-05");
    vi.useRealTimers();
  });

  it.each(["abc", "1,5", "1.", ".5", "1.1234567", "1234567890123", "-5"])(
    "refuses %j before any request, without converting it",
    async (text) => {
      const recorded = api();
      const { container } = renderForm();
      await submit(text);
      expect(await screen.findByText(en.readingForm.valueFormat)).toBeInTheDocument();
      expect(value()).toHaveFocus();
      expect(value()).toHaveValue(text);
      expect(recorded.lookups).toEqual([]);
      expect(recorded.posts).toEqual([]);
      expect(await axeViolations(container)).toEqual([]);
    },
  );
});

describe("the request", () => {
  it("sends date only values unconverted, with a key", async () => {
    const recorded = api();
    renderForm();
    await submit("13049.50");
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toEqual([{ cumulative_kwh: "13049.50", local_date: TODAY }]);
    expect(recorded.keys[0]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("sends a date and time through the property's zone", async () => {
    const recorded = api();
    renderForm();
    const user = userEvent.setup();
    await user.type(time(), "09:30");
    await submit("100", user);
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toEqual([
      { cumulative_kwh: "100", recorded_at: "2026-11-04T14:30:00Z" },
    ]);
  });
});

describe("the lower value warning", () => {
  const earlier = reading({ id: "r-old", cumulative_kwh: "13049.000000" });

  it("looks up the nearest earlier valid reading at noon for a date only entry", async () => {
    const recorded = api();
    renderForm();
    await submit("100");
    await screen.findByText(en.readingForm.saved);
    const params = recorded.lookups[0];
    expect(params.get("order")).toBe("desc");
    expect(params.get("status")).toBe("valid");
    expect(params.get("limit")).toBe("1");
    // Noon on Nov 4 in New York, EST.
    expect(params.get("to")).toBe("2026-11-04T17:00:00Z");
  });

  it("uses the entered time for a date and time entry", async () => {
    const recorded = api();
    renderForm();
    const user = userEvent.setup();
    await user.type(time(), "08:00");
    await submit("100", user);
    await screen.findByText(en.readingForm.saved);
    expect(recorded.lookups[0].get("to")).toBe("2026-11-04T13:00:00Z");
  });

  it("warns, saves nothing, and moves focus to the alert", async () => {
    const recorded = api({ earlier });
    const { container } = renderForm();
    await submit("13012");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.readingForm.warningTitle);
    expect(alert).toHaveTextContent("13,049 kWh on November 4, 2026");
    expect(alert).toHaveTextContent(en.readingForm.warningAfter);
    await waitFor(() => expect(alert).toHaveFocus());
    expect(recorded.posts).toEqual([]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is an exact comparison, not a float or text one", async () => {
    const recorded = api({ earlier: reading({ cumulative_kwh: "10.000000" }) });
    renderForm();
    await submit("9.5");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(recorded.posts).toEqual([]);
  });

  it.each([
    ["equal", "13049"],
    ["equal with trailing zeros", "13049.000000"],
    ["above its earlier neighbor", "13050"],
  ])("does not warn when %s", async (_name, text) => {
    const recorded = api({ earlier });
    renderForm();
    await submit(text);
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toHaveLength(1);
  });

  it("does not warn with no earlier reading", async () => {
    const recorded = api({ earlier: null });
    renderForm();
    await submit("1");
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toHaveLength(1);
  });

  it("saves with no warning when the lookup fails for any reason but 401", async () => {
    const recorded = api({ lookup: () => problem(503, "database_unavailable") });
    renderForm();
    await submit("1");
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toHaveLength(1);
  });

  it("saves nothing when the lookup says the session is gone", async () => {
    const recorded = api({ lookup: () => problem(401, "not_authenticated") });
    renderForm();
    await submit("1");
    await waitFor(() => expect(recorded.lookups).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(recorded.posts).toEqual([]);
    expect(screen.queryByText(en.readingForm.saved)).toBeNull();
  });

  it("Save anyway saves with the same key as the warned submission", async () => {
    let fail = true;
    const recorded = api({
      earlier,
      save: () =>
        fail ? problem(503, "database_unavailable") : HttpResponse.json(reading(), { status: 201 }),
    });
    renderForm();
    const user = await submit("13012");
    await user.click(await screen.findByRole("button", { name: en.readingForm.saveAnyway }));
    await screen.findByText(en.readingForm.notSaved);
    fail = false;
    await user.click(screen.getByRole("button", { name: en.readingForm.saveAnyway }));
    await screen.findByText(en.readingForm.saved);
    expect(recorded.keys).toHaveLength(2);
    expect(recorded.keys[1]).toBe(recorded.keys[0]);
  });

  it("drops a lookup result when the user edits while it runs, and saves nothing", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const recorded = api({
      lookup: async () => {
        await gate;
        return HttpResponse.json({ items: [earlier], next_cursor: null });
      },
    });
    renderForm();
    const user = userEvent.setup();
    await user.type(value(), "13012");
    await user.click(screen.getByRole("button", { name: en.readingForm.submit }));
    await waitFor(() => expect(recorded.lookups).toHaveLength(1));
    await user.type(value(), "9"); // edited while the lookup is still running
    release();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("button", { name: en.readingForm.saveAnyway })).toBeNull();
    expect(recorded.posts).toEqual([]);
    expect(value()).toHaveValue("130129");
  });

  it("Save anyway saves the values that were warned about", async () => {
    const recorded = api({ earlier });
    renderForm();
    const user = await submit("13012");
    await user.click(await screen.findByRole("button", { name: en.readingForm.saveAnyway }));
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toHaveLength(1);
    expect(JSON.stringify(recorded.posts[0])).toContain("13012");
  });

  it("Change value clears the warning and returns to the value", async () => {
    const recorded = api({ earlier });
    renderForm();
    const user = await submit("13012");
    await user.click(await screen.findByRole("button", { name: en.readingForm.changeValue }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(value()).toHaveFocus();
    expect(recorded.posts).toEqual([]);
  });

  it.each([
    ["value", () => value(), "5"],
    ["time", () => time(), "08:00"],
  ])("editing the %s clears the warning", async (_name, field, text) => {
    api({ earlier });
    renderForm();
    const user = await submit("13012");
    await screen.findByRole("alert");
    await user.type(field(), text);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: en.readingForm.submit })).toBeInTheDocument();
  });

  it("the link scrolls to and focuses the row when it is loaded", async () => {
    api({ earlier });
    renderWithClient(
      <>
        <ReadingForm meterId={METER} zone={ZONE} today={TODAY} window={WINDOW} />
        <ul>
          {}
          <li id="reading-r-old" tabIndex={-1}>
            row
          </li>
        </ul>
      </>,
    );
    Element.prototype.scrollIntoView = vi.fn();
    const user = await submit("13012");
    await user.click(await screen.findByRole("link", { name: /13,049 kWh/ }));
    expect(document.getElementById("reading-r-old")).toHaveFocus();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("keeps the earlier row focused if the warning focus frame runs after the link click", async () => {
    api({ earlier });
    renderWithClient(
      <>
        <ReadingForm meterId={METER} zone={ZONE} today={TODAY} window={WINDOW} />
        <ul>
          <li id="reading-r-old" tabIndex={-1}>
            row
          </li>
        </ul>
      </>,
    );
    Element.prototype.scrollIntoView = vi.fn();
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.push(callback);
      return frames.length;
    });

    const user = await submit("13012");
    await user.click(await screen.findByRole("link", { name: /13,049 kWh/ }));
    const row = document.getElementById("reading-r-old");
    expect(row).toHaveFocus();
    expect(frames).toHaveLength(1);
    frames[0](0);
    expect(row).toHaveFocus();
  });
});

describe("save results", () => {
  it("clears the value and time, keeps the date, announces, and returns focus", async () => {
    api();
    const { client } = renderForm();
    const key = getStoredConsumptionQueryKey(METER, WINDOW);
    const list = readingsListOptions(METER).queryKey;
    client.setQueryData(key, { ok: true });
    client.setQueryData(list, { pages: [], pageParams: [] });
    const user = userEvent.setup();
    await user.clear(date());
    await user.type(date(), "2026-11-01");
    await user.type(time(), "09:30");
    await submit("100", user);

    const status = await screen.findByText(en.readingForm.saved);
    expect(status.closest("[role=status]")).not.toBeNull();
    expect(value()).toHaveValue("");
    expect(time()).toHaveValue("");
    expect(date()).toHaveValue("2026-11-01");
    await waitFor(() => expect(value()).toHaveFocus());
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    expect(client.getQueryState(list)?.isInvalidated).toBe(true);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("makes a new key after success", async () => {
    const recorded = api();
    renderForm();
    const user = await submit("100");
    await screen.findByText(en.readingForm.saved);
    await submit("100", user);
    await waitFor(() => expect(recorded.keys).toHaveLength(2));
    expect(recorded.keys[1]).not.toBe(recorded.keys[0]);
  });

  it("refreshes the page when the reading falls at or past the window's end", async () => {
    api({
      save: () =>
        HttpResponse.json(reading({ recorded_at: WINDOW.to }), {
          status: 201,
        }),
    });
    renderForm();
    await submit("100");
    await screen.findByText(en.readingForm.saved);
    expect(router.refresh).toHaveBeenCalledOnce();
  });

  it("shows a same instant conflict on the date", async () => {
    api({ save: () => problem(409, "reading_exists_at_instant", { existing_reading_id: "x" }) });
    const { container } = renderForm();
    await submit("100");
    expect(await screen.findByText(en.readingForm.exists)).toBeInTheDocument();
    expect(date()).toHaveFocus();
    expect(date()).toHaveAttribute("aria-invalid", "true");
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["local_date", () => date()],
    ["recorded_at", () => time()],
  ])("shows reading_in_future at %s by its loc", async (field, control) => {
    api({
      save: () =>
        problem(422, "validation_failed", {
          errors: [{ loc: ["body", field], code: "reading_in_future", message: "no" }],
        }),
    });
    renderForm();
    await submit("100");
    expect(await screen.findByText(en.fieldErrors.reading_in_future)).toBeInTheDocument();
    expect(control()).toHaveFocus();
  });

  it("shows invalid_kwh on the value", async () => {
    api({
      save: () =>
        problem(422, "validation_failed", {
          errors: [{ loc: ["body", "cumulative_kwh"], code: "invalid_kwh", message: "no" }],
        }),
    });
    renderForm();
    await submit("100");
    await waitFor(() => expect(value()).toHaveAttribute("aria-invalid", "true"));
  });

  it("shows an inactive meter as a form alert and refetches the meter", async () => {
    api({ save: () => problem(409, "meter_inactive") });
    const { client, onInactive } = renderForm();
    client.setQueryData(getGetMeterQueryKey(METER), { active: true });
    await submit("100");
    expect(await screen.findByText(en.readingForm.inactiveTitle)).toBeInTheDocument();
    expect(onInactive).toHaveBeenCalledOnce();
    expect(client.getQueryState(getGetMeterQueryKey(METER))?.isInvalidated).toBe(true);
    expect(screen.getByRole("button", { name: en.readingForm.submit })).toBeDisabled();
    expect(value()).toHaveValue("100");
  });

  it("keeps the typed values on an outage and reuses the key on retry", async () => {
    let fail = true;
    const recorded = api({
      save: () =>
        fail ? problem(503, "database_unavailable") : HttpResponse.json(reading(), { status: 201 }),
    });
    const { container } = renderForm();
    const user = await submit("100.5");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.unavailable.message);
    await waitFor(() => expect(alert).toHaveFocus());
    expect(value()).toHaveValue("100.5");
    expect(await axeViolations(container)).toEqual([]);

    fail = false;
    await user.click(screen.getByRole("button", { name: en.readingForm.submit }));
    await screen.findByText(en.readingForm.saved);
    expect(recorded.keys[1]).toBe(recorded.keys[0]);
  });

  it("makes a new key when the value changes before the retry", async () => {
    const recorded = api({ save: () => problem(503, "database_unavailable") });
    renderForm();
    const user = await submit("100");
    await screen.findByRole("alert");
    await submit("101", user);
    await waitFor(() => expect(recorded.keys).toHaveLength(2));
    expect(recorded.keys[1]).not.toBe(recorded.keys[0]);
  });

  it("blocks a double submit", async () => {
    let release: (value: Response) => void = () => undefined;
    const recorded = api({ save: () => new Promise((resolve) => (release = resolve)) });
    renderForm();
    const user = await submit("100");
    const pending = await screen.findByRole("button", { name: en.readingForm.pending });
    expect(pending).toBeDisabled();
    await user.click(pending);
    await waitFor(() => expect(recorded.posts).toHaveLength(1));
    release(HttpResponse.json(reading(), { status: 201 }));
    await screen.findByText(en.readingForm.saved);
    expect(recorded.posts).toHaveLength(1);
  });

  it("is clean under axe when idle", async () => {
    const { container } = renderForm();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("an inactive meter", () => {
  it("replaces the form with a note, keeping the rest", async () => {
    server.use(
      http.get(`*/api/v1/meters/${METER}`, () => HttpResponse.json({ id: METER, active: false })),
      http.get(READINGS, () => HttpResponse.json({ items: [reading()], next_cursor: null })),
      http.get(`*/api/v1/meters/${METER}/consumption`, () => new Promise(() => undefined)),
    );
    const { client } = renderWithClient(
      <MeterScreen meterId={METER} zone={ZONE} today={TODAY} range="90d" window={WINDOW} />,
    );
    client.setQueryData(getGetMeterQueryKey(METER), { id: METER, active: false });
    expect(await screen.findByText(en.inactiveMeter.title)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: en.readingForm.submit })).toBeNull();
    expect(await screen.findByRole("button", { name: /^Void 13,049 kWh/ })).toBeInTheDocument();
  });
});
