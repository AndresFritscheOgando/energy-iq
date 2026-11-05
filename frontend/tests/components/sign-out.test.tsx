/** Sign out (spec 0010 AC-9). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { SignOutButton } from "@/components/auth/SignOutButton";
import { CSRF_HEADER } from "@/lib/api/fetcher";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { renderWithClient } from "./render";

const LOGOUT = "*/api/v1/auth/logout";

describe("SignOutButton", () => {
  it("on 204 clears the cache and fully navigates to /login", async () => {
    let csrf: string | null = null;
    server.use(
      http.post(LOGOUT, ({ request }) => {
        csrf = request.headers.get(CSRF_HEADER);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const navigate = vi.fn();
    const { clear } = renderWithClient(<SignOutButton navigate={navigate} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login"));
    expect(clear).toHaveBeenCalled();
    expect(csrf).toBe("1");
  });

  it.each([
    [
      "csrf_rejected",
      () => problem(403, "csrf_rejected"),
      "This page was opened from an address EnergyIQ does not trust.",
    ],
    ["an outage", () => HttpResponse.error(), "EnergyIQ can't reach its server right now."],
    [
      "a database_unavailable 503",
      () => problem(503, "database_unavailable"),
      "EnergyIQ can't reach its server right now.",
    ],
  ])("on %s stays signed in and shows an inline alert", async (_name, respond, message) => {
    server.use(http.post(LOGOUT, respond));
    const navigate = vi.fn();
    const { clear } = renderWithClient(<SignOutButton navigate={navigate} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(navigate).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
  });
});
