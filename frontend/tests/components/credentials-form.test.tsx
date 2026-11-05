/**
 * Login and register forms (spec 0010 AC-7, AC-8, AC-15): error placement,
 * focus, pending state, and axe in the idle, field error, and form error
 * states.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CredentialsForm, passwordLength } from "@/components/auth/CredentialsForm";
import { CSRF_HEADER } from "@/lib/api/fetcher";
import { en } from "@/messages/en";

import { problem, USER } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const LOGIN = "*/api/v1/auth/login";
const REGISTER = "*/api/v1/auth/register";
const PASSWORD = "correct horse battery";

beforeEach(() => {
  router.replace.mockReset();
});

async function fill(email: string, password: string) {
  const user = userEvent.setup();
  if (email) {
    await user.type(screen.getByLabelText("Email"), email);
  }
  if (password) {
    await user.type(screen.getByLabelText("Password"), password);
  }
  return user;
}

async function submit(mode: "login" | "register", email = USER.email, password = PASSWORD) {
  const user = await fill(email, password);
  await user.click(
    screen.getByRole("button", { name: mode === "login" ? "Sign in" : "Create account" }),
  );
  return user;
}

describe("credentials forms before hydration", () => {
  it.each(["login", "register"] as const)(
    "%s form never falls back to a GET that puts credentials in the URL",
    (mode) => {
      const { container } = renderWithClient(<CredentialsForm mode={mode} next="/" />);
      expect(container.querySelector("form")?.getAttribute("method")).toBe("post");
    },
  );
});

describe("login form", () => {
  it("has labelled inputs and no axe violations when idle", async () => {
    const { container } = renderWithClient(<CredentialsForm mode="login" next="/" />);

    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("signs in with the CSRF header and goes to the safe next path", async () => {
    let seen: Request | undefined;
    server.use(
      http.post(LOGIN, ({ request }) => {
        seen = request;
        return HttpResponse.json(USER);
      }),
    );
    const { clear } = renderWithClient(<CredentialsForm mode="login" next="/properties?x=1" />);

    await submit("login");

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/properties?x=1"));
    expect(seen?.headers.get(CSRF_HEADER)).toBe("1");
    expect(await seen?.json()).toEqual({ email: USER.email, password: PASSWORD });
    expect(clear).toHaveBeenCalled();
  });

  it("shows invalid_credentials once, on no field, and focuses the alert", async () => {
    server.use(http.post(LOGIN, () => problem(401, "invalid_credentials")));
    const { container } = renderWithClient(<CredentialsForm mode="login" next="/" />);

    await submit("login");

    const alert = await screen.findByText("Email or password is incorrect.");
    const box = alert.closest('[role="alert"]');
    expect(box).not.toBeNull();
    await waitFor(() => expect(box).toHaveFocus());
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "false");
    expect(screen.getAllByText("Email or password is incorrect.")).toHaveLength(1);
    expect(container.textContent).not.toContain("Server detail text");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("puts a 422 password_length on the password input and focuses it", async () => {
    server.use(
      http.post(LOGIN, () =>
        problem(422, "validation_error", {
          errors: [{ loc: ["body", "password"], code: "password_length", message: "SERVER TEXT" }],
        }),
      ),
    );
    const { container } = renderWithClient(<CredentialsForm mode="login" next="/" />);

    await submit("login", USER.email, "short");

    const password = screen.getByLabelText("Password");
    await waitFor(() => expect(password).toHaveAttribute("aria-invalid", "true"));
    expect(password).toHaveFocus();
    expect(password).toHaveAccessibleDescription(en.fieldErrors.password_length);
    expect(container.textContent).not.toContain("SERVER TEXT");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the 429 wait in whole minutes", async () => {
    server.use(
      http.post(LOGIN, () => problem(429, "too_many_attempts", {}, { "Retry-After": "540" })),
    );
    renderWithClient(<CredentialsForm mode="login" next="/" />);

    await submit("login");

    expect(await screen.findByText("Too many attempts. Try again in 9 minutes.")).toBeVisible();
  });

  it("shows the unavailable message inline when the API is down", async () => {
    server.use(http.post(LOGIN, () => HttpResponse.error()));
    renderWithClient(<CredentialsForm mode="login" next="/" />);

    await submit("login");

    expect(await screen.findByText("EnergyIQ can't reach its server right now.")).toBeVisible();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("blocks empty fields on the client and focuses the first one", async () => {
    let calls = 0;
    server.use(
      http.post(LOGIN, () => {
        calls += 1;
        return HttpResponse.json(USER);
      }),
    );
    const { container } = renderWithClient(<CredentialsForm mode="login" next="/" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const email = screen.getByLabelText("Email");
    await waitFor(() => expect(email).toHaveFocus());
    expect(email).toHaveAccessibleDescription(en.required.email);
    expect(calls).toBe(0);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows a pending state and blocks a double submit", async () => {
    let calls = 0;
    server.use(
      http.post(LOGIN, async () => {
        calls += 1;
        await delay(50);
        return HttpResponse.json(USER);
      }),
    );
    renderWithClient(<CredentialsForm mode="login" next="/" />);
    const user = await fill(USER.email, PASSWORD);
    const button = screen.getByRole("button", { name: "Sign in" });

    await user.click(button);
    await user.click(button);

    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(calls).toBe(1);
  });
});

describe("register form", () => {
  it("hints the NFKC length without blocking submit", async () => {
    let posted: unknown;
    server.use(
      http.post(REGISTER, async ({ request }) => {
        posted = await request.json();
        return problem(422, "validation_error", {
          errors: [{ loc: ["body", "password"], code: "password_length", message: "x" }],
        });
      }),
    );
    const { container } = renderWithClient(<CredentialsForm mode="register" next="/" />);

    expect(screen.getByText("Use 12 to 128 characters. You have 0 characters.")).toBeVisible();
    expect(await axeViolations(container)).toEqual([]);

    // Case is kept; the server normalizes. (Browsers strip outer spaces
    // from an email input's value themselves.)
    await submit("register", "Owner@Example.TEST", "short");

    expect(screen.getByText("Use 12 to 128 characters. You have 5 characters.")).toBeVisible();
    await waitFor(() => expect(posted).toEqual({ email: "Owner@Example.TEST", password: "short" }));
  });

  it("counts characters after NFKC normalization", () => {
    expect(passwordLength("ﬁ")).toBe(2);
    expect(passwordLength("é")).toBe(1);
    expect(passwordLength("😀")).toBe(1);
  });

  it("goes home after a 201", async () => {
    server.use(http.post(REGISTER, () => HttpResponse.json(USER, { status: 201 })));
    renderWithClient(<CredentialsForm mode="register" next="/ignored" />);

    await submit("register");

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  it("shows email_taken on the email field with a link to sign in", async () => {
    server.use(http.post(REGISTER, () => problem(409, "email_taken")));
    const { container } = renderWithClient(<CredentialsForm mode="register" next="/" />);

    await submit("register");

    const email = screen.getByLabelText("Email");
    await waitFor(() => expect(email).toHaveAttribute("aria-invalid", "true"));
    expect(email).toHaveFocus();
    expect(email).toHaveAccessibleDescription(
      expect.stringContaining("An account with this email already exists."),
    );
    expect(screen.getByRole("link", { name: "Sign in instead" })).toHaveAttribute("href", "/login");
    expect(await axeViolations(container)).toEqual([]);
  });
});
