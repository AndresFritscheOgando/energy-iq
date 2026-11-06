/**
 * Home and property: lists, create forms, and their error states (spec 0011
 * child 0001 AC-2 to AC-5, AC-12).
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateMeterForm } from "@/components/meters/CreateMeterForm";
import { MeterList } from "@/components/meters/MeterList";
import { CreatePropertyForm } from "@/components/properties/CreatePropertyForm";
import { PropertyList } from "@/components/properties/PropertyList";
import { getListMetersQueryKey } from "@/lib/api/generated/meters/meters";
import { getListPropertiesQueryKey } from "@/lib/api/generated/properties/properties";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const PROPERTIES = "*/api/v1/properties";
const PROPERTY_ID = "00000000-0000-4000-8000-000000000001";
const METERS = `*/api/v1/properties/${PROPERTY_ID}/meters`;

beforeEach(() => router.push.mockReset());

function property(id: string, nickname: string, region: string | null = null) {
  return {
    id,
    nickname,
    region,
    timezone: "America/Santo_Domingo",
    created_at: "",
    updated_at: "",
  };
}

describe("PropertyList", () => {
  it("links each property and shows its region when set", async () => {
    server.use(
      http.get(PROPERTIES, () =>
        HttpResponse.json({
          items: [property("a", "Demo home", "Santo Domingo"), property("b", "Workshop")],
          next_cursor: null,
        }),
      ),
    );
    renderWithClient(<PropertyList />);
    const link = await screen.findByRole("link", { name: /Demo home/ });
    expect(link).toHaveAttribute("href", "/properties/a");
    expect(link).toHaveTextContent("Santo Domingo");
    expect(screen.queryByRole("button", { name: en.lists.loadMore })).toBeNull();
  });

  it("shows an empty state", async () => {
    server.use(http.get(PROPERTIES, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderWithClient(<PropertyList />);
    expect(await screen.findByText(en.home.emptyTitle)).toBeInTheDocument();
  });

  it("shows a failed first page with Retry, which recovers", async () => {
    let fail = true;
    server.use(
      http.get(PROPERTIES, () =>
        fail
          ? problem(500, "internal_error")
          : HttpResponse.json({ items: [property("a", "Home")], next_cursor: null }),
      ),
    );
    const { container } = renderWithClient(<PropertyList />);
    const retry = await screen.findByRole("button", { name: en.lists.retry });
    expect(screen.getByRole("alert")).toHaveTextContent("req-123");
    expect(await axeViolations(container)).toEqual([]);

    fail = false;
    await userEvent.setup().click(retry);
    expect(await screen.findByRole("link", { name: /Home/ })).toBeInTheDocument();
  });

  it("appends the next page, and a failed Load more keeps the rows", async () => {
    let calls = 0;
    server.use(
      http.get(PROPERTIES, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        calls += 1;
        if (cursor === null) {
          return HttpResponse.json({ items: [property("a", "First")], next_cursor: "next" });
        }
        return calls === 2
          ? problem(500, "internal_error")
          : HttpResponse.json({ items: [property("b", "Second")], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<PropertyList />);
    await user.click(await screen.findByRole("button", { name: en.lists.loadMore }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.lists.loadFailed);
    expect(screen.getByRole("link", { name: /First/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: en.lists.retry }));
    expect(await screen.findByRole("link", { name: /Second/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /First/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("has no axe violations while loading", async () => {
    server.use(http.get(PROPERTIES, () => new Promise(() => undefined)));
    const { container } = renderWithClient(<PropertyList />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("CreatePropertyForm", () => {
  async function submit(nickname = "Home", region = "") {
    const user = userEvent.setup();
    if (nickname) {
      await user.type(screen.getByLabelText(en.propertyForm.nickname), nickname);
    }
    if (region) {
      await user.type(screen.getByLabelText(/Region/), region);
    }
    await user.click(screen.getByRole("button", { name: en.propertyForm.submit }));
    return user;
  }

  it("creates, invalidates the list, and opens the property", async () => {
    const bodies: unknown[] = [];
    const keys: (string | null)[] = [];
    server.use(
      http.post(PROPERTIES, async ({ request }) => {
        bodies.push(await request.json());
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(property("new-id", "Home"), { status: 201 });
      }),
    );
    const { client } = renderWithClient(<CreatePropertyForm />);
    client.setQueryData(getListPropertiesQueryKey({ limit: 50 }), { items: [] });
    await submit();

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/properties/new-id"));
    expect(bodies).toEqual([{ nickname: "Home" }]);
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    const state = client.getQueryState(getListPropertiesQueryKey({ limit: 50 }));
    expect(state?.isInvalidated).toBe(true);
  });

  it("sends a region when set, and has no time zone field", async () => {
    let body: unknown;
    server.use(
      http.post(PROPERTIES, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(property("x", "Home"), { status: 201 });
      }),
    );
    renderWithClient(<CreatePropertyForm />);
    expect(screen.queryByLabelText(/zone/i)).toBeNull();
    await submit("Home", "Santiago");
    await waitFor(() => expect(body).toEqual({ nickname: "Home", region: "Santiago" }));
  });

  it("requires a nickname without a request, and focuses it", async () => {
    const { container } = renderWithClient(<CreatePropertyForm />);
    expect(await axeViolations(container)).toEqual([]);
    await submit("");
    const input = screen.getByLabelText(en.propertyForm.nickname);
    expect(await screen.findByText(en.propertyForm.nicknameRequired)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveFocus();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows a name conflict on the nickname, and maps 422 errors to fields", async () => {
    server.use(http.post(PROPERTIES, () => problem(409, "property_name_taken")));
    renderWithClient(<CreatePropertyForm />);
    const user = await submit();
    expect(await screen.findByText(en.propertyForm.nameTaken)).toBeInTheDocument();
    expect(screen.getByLabelText(en.propertyForm.nickname)).toHaveFocus();

    server.use(
      http.post(PROPERTIES, () =>
        problem(422, "validation_failed", {
          errors: [{ loc: ["body", "region"], code: "invalid_text_length", message: "no" }],
        }),
      ),
    );
    await user.click(screen.getByRole("button", { name: en.propertyForm.submit }));
    expect(await screen.findByText(en.fieldErrors.invalid_text_length)).toBeInTheDocument();
    expect(screen.getByLabelText(/Region/)).toHaveFocus();
  });

  it("shows a form alert on an outage, with focus, and reuses the key on retry", async () => {
    const keys: (string | null)[] = [];
    let fail = true;
    server.use(
      http.post(PROPERTIES, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return fail
          ? problem(503, "database_unavailable")
          : HttpResponse.json(property("x", "Home"), { status: 201 });
      }),
    );
    const { container } = renderWithClient(<CreatePropertyForm />);
    const user = await submit();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.unavailable.message);
    await waitFor(() => expect(alert).toHaveFocus());
    expect(await axeViolations(container)).toEqual([]);

    fail = false;
    await user.click(screen.getByRole("button", { name: en.propertyForm.submit }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });
});

describe("MeterList", () => {
  it("shows all meters with an Inactive marker, asking for inactive ones", async () => {
    let includeInactive: string | null = null;
    server.use(
      http.get(METERS, ({ request }) => {
        includeInactive = new URL(request.url).searchParams.get("include_inactive");
        return HttpResponse.json({
          items: [
            { id: "m1", label: "Main", distributor: "EDESUR", active: true },
            { id: "m2", label: "Old", distributor: "OTHER", active: false },
          ],
          next_cursor: null,
        });
      }),
    );
    renderWithClient(<MeterList propertyId={PROPERTY_ID} />);
    const old = await screen.findByRole("link", { name: /Old/ });
    expect(old).toHaveAttribute("href", "/meters/m2");
    expect(old).toHaveTextContent("Other");
    expect(old).toHaveTextContent(en.property.inactive);
    expect(screen.getByRole("link", { name: /Main/ })).not.toHaveTextContent(en.property.inactive);
    expect(includeInactive).toBe("true");
  });

  it("shows an empty state", async () => {
    server.use(http.get(METERS, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderWithClient(<MeterList propertyId={PROPERTY_ID} />);
    expect(await screen.findByText(en.property.emptyTitle)).toBeInTheDocument();
  });
});

describe("CreateMeterForm", () => {
  async function submit(label = "Main", distributor: string | null = "OTHER") {
    const user = userEvent.setup();
    if (label) {
      await user.type(screen.getByLabelText(en.meterForm.label), label);
    }
    if (distributor) {
      await user.selectOptions(screen.getByLabelText(en.meterForm.distributor), distributor);
    }
    await user.click(screen.getByRole("button", { name: en.meterForm.submit }));
    return user;
  }

  it("has a native select with the four labels and no register digits", () => {
    renderWithClient(<CreateMeterForm propertyId={PROPERTY_ID} />);
    const select = screen.getByLabelText(en.meterForm.distributor) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("");
    expect([...select.options].map((option) => option.text).slice(1)).toEqual([
      "EDESUR",
      "EDEESTE",
      "EDENORTE",
      "Other",
    ]);
    expect(screen.queryByLabelText(/digits/i)).toBeNull();
  });

  it("requires a distributor, with no default", async () => {
    renderWithClient(<CreateMeterForm propertyId={PROPERTY_ID} />);
    await submit("Main", null);
    expect(await screen.findByText(en.meterForm.distributorRequired)).toBeInTheDocument();
    expect(screen.getByLabelText(en.meterForm.distributor)).toHaveFocus();
  });

  it("sends the enum value, invalidates the property's list, and opens the meter", async () => {
    let body: unknown;
    server.use(
      http.post(METERS, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "meter-new" }, { status: 201 });
      }),
    );
    const { client } = renderWithClient(<CreateMeterForm propertyId={PROPERTY_ID} />);
    const key = getListMetersQueryKey(PROPERTY_ID, { include_inactive: true, limit: 50 });
    client.setQueryData(key, { items: [] });
    await submit();
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/meters/meter-new"));
    expect(body).toEqual({ label: "Main", distributor: "OTHER" });
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it("shows a label conflict on the label field", async () => {
    server.use(http.post(METERS, () => problem(409, "meter_label_taken")));
    renderWithClient(<CreateMeterForm propertyId={PROPERTY_ID} />);
    await submit();
    expect(await screen.findByText(en.meterForm.labelTaken)).toBeInTheDocument();
    expect(screen.getByLabelText(en.meterForm.label)).toHaveFocus();
  });

  it("shows an archived property as a form alert with a link home", async () => {
    server.use(http.post(METERS, () => problem(404, "not_found")));
    const { container } = renderWithClient(<CreateMeterForm propertyId={PROPERTY_ID} />);
    await submit();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.meterForm.propertyGone);
    expect(screen.getByRole("link", { name: en.meterForm.goHome })).toHaveAttribute("href", "/");
    expect(await axeViolations(container)).toEqual([]);
  });
});
