/**
 * The product in a real browser (spec 0011 child 0003 AC-5). J1 is the Phase 3
 * exit gate. J7 is covered by Vitest (child 0002 AC-10), since a browser can't
 * intercept a server call.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { API_ORIGIN } from "./constants.mjs";
import {
  PASSWORD,
  PRISTINE_STATE,
  SHARED_INFO,
  SHARED_STATE,
  addReading,
  chart,
  createMeter,
  daysAgo,
  expect,
  expectStepDrawn,
  intervals,
  submitReading,
  test,
  uniqueEmail,
  uniqueName,
  waitForPlot,
} from "./support";

test.describe("J1 gate", () => {
  test("register to a measured step through the same origin proxy", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Email").fill(uniqueEmail("gate"));
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByRole("heading", { name: "No properties yet" })).toBeVisible();
    const nickname = uniqueName("Home");
    await page.getByLabel("Nickname").fill(nickname);
    await page.getByLabel("Region").fill("Santo Domingo");
    await page.getByRole("button", { name: "Add property" }).click();
    await expect(page.getByRole("heading", { name: nickname, level: 1 })).toBeVisible();
    await expect(page).toHaveURL(/\/properties\/[0-9a-f-]+$/);

    const label = uniqueName("Meter");
    await expect(page.getByRole("heading", { name: "No meters yet" })).toBeVisible();
    await page.getByLabel("Label").fill(label);
    await page.getByLabel("Distributor").selectOption("OTHER");
    await page.getByRole("button", { name: "Add meter" }).click();
    await expect(page.getByRole("heading", { name: label, level: 1 })).toBeVisible();
    await expect(page).toHaveURL(/\/meters\/[0-9a-f-]+$/);

    await submitReading(page, "100", 10);
    await expect(page.getByText("Reading saved")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Add at least two readings to see usage" }),
    ).toBeVisible();
    await expect(chart(page)).toHaveCount(0);

    // 10 days at 2.5 kWh per day.
    await submitReading(page, "125", 0);
    await waitForPlot(page);
    await expectStepDrawn(page);
    await expect(page.getByText("25.00").first()).toBeVisible();
    const row = intervals(page).locator('tr[data-kind="step"]');
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("25.00");
    await expect(row).toContainText("2.50");
    await expect(row).toContainText("Average over 10 days");
    await expect(page.getByTestId("chart-readout")).toContainText("2.50 kWh per day, 25.00 kWh");
  });
});

test.describe("signed in as shared", () => {
  test.use({ storageState: SHARED_STATE });

  test("J2 a lower value warns, saves, shows a band, and voiding removes the gap", async ({
    page,
  }) => {
    const { meterId } = await createMeter(page, [
      [20, "1000"],
      [10, "1100"],
    ]);
    await page.goto(`/meters/${meterId}`);
    await waitForPlot(page);
    await expect(chart(page).locator(".chart-band--invalid")).toHaveCount(0);

    await submitReading(page, "1050", 0);
    const warning = page.getByRole("alert").filter({ hasText: "Lower than an earlier reading" });
    await expect(warning).toContainText("1,100 kWh");
    await expect(page.getByRole("list", { name: "Readings" }).getByRole("listitem")).toHaveCount(2);

    await warning.getByRole("button", { name: "Save anyway" }).click();
    await expect(page.getByText("Reading saved")).toBeVisible();
    await expect(chart(page).locator(".chart-band--invalid")).toHaveCount(1);
    const note = "The reading dropped with no recorded reset or replacement";
    await expect(intervals(page)).toContainText(note);

    await page.getByRole("button", { name: /^Void 1,050 kWh/ }).click();
    await page.getByRole("button", { name: "Void reading" }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(chart(page).locator(".chart-band--invalid")).toHaveCount(0);
    await expect(intervals(page)).not.toContainText(note);
    await expect(page.getByRole("list", { name: "Readings" })).toContainText("Voided");
  });

  test("J3 zero use is a step on the baseline, a gap has hatching and no number", async ({
    page,
  }) => {
    const { meterId } = await createMeter(page, [
      [14, "500"],
      [7, "500"],
    ]);
    await page.goto(`/meters/${meterId}`);
    await waitForPlot(page);

    await expect(chart(page).locator(".chart-zero rect").first()).toBeVisible();
    const zero = intervals(page).locator('tr[data-kind="zero"]');
    await expect(zero).toHaveCount(1);
    await expect(zero).toContainText("0.00");

    const after = intervals(page)
      .locator('tr[data-kind="gap"]')
      .filter({ hasText: "No reading yet after this date." });
    await expect(after).toContainText("No measured usage");
    await expect(after).not.toContainText("0.00");
    // Every band is hatched; none sits over the zero step's span.
    await expect(chart(page).locator(".chart-band").first()).toBeVisible();
    const fills = await chart(page)
      .locator(".chart-band rect")
      .evaluateAll((rects) => rects.map((rect) => rect.getAttribute("fill")));
    expect(fills.every((fill) => fill?.startsWith("url(#hatch-gap"))).toBe(true);
  });

  test("J4 ranges change the URL and content, back returns, a bad range is 90 days", async ({
    page,
  }) => {
    const { meterId } = await createMeter(page, [
      [200, "100"],
      [190, "150"],
    ]);
    await page.goto(`/meters/${meterId}`);
    const nav = page.getByRole("navigation", { name: "Range" });
    await expect(nav.getByRole("link", { name: "90 days" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByText("No usage is measured in the last 90 days.")).toBeVisible();

    await page.getByRole("link", { name: "Show the last 365 days" }).click();
    await expect(page).toHaveURL(/range=365d/);
    await expect(nav.getByRole("link", { name: "365 days" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(intervals(page).locator('tr[data-kind="step"]')).toHaveCount(1);
    await expect(page.getByText("No usage is measured")).toHaveCount(0);

    await page.goBack();
    await expect(page).not.toHaveURL(/range=365d/);
    await expect(page.getByText("No usage is measured in the last 90 days.")).toBeVisible();

    await page.goto(`/meters/${meterId}?range=bogus`);
    await expect(nav.getByRole("link", { name: "90 days" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("J5 saving a reading updates the chart with no reload", async ({ page }) => {
    const { meterId } = await createMeter(page, [
      [20, "100"],
      [10, "120"],
    ]);
    await page.goto(`/meters/${meterId}`);
    await waitForPlot(page);
    await page.evaluate(() => {
      (window as unknown as { marker: string }).marker = "same page";
    });
    await expect(intervals(page).locator('tr[data-kind="step"]')).toHaveCount(1);

    await submitReading(page, "140", 0);
    await expect(intervals(page).locator('tr[data-kind="step"]')).toHaveCount(2);
    expect(await page.evaluate(() => (window as unknown as { marker: string }).marker)).toBe(
      "same page",
    );
  });

  test("J6 a failed refresh marks the old chart out of date, and Retry recovers", async ({
    page,
  }) => {
    const { meterId } = await createMeter(page, [
      [20, "100"],
      [10, "120"],
    ]);
    await page.goto(`/meters/${meterId}`);
    await waitForPlot(page);

    const pattern = `**/api/v1/meters/${meterId}/consumption*`;
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/problem+json",
        body: JSON.stringify({
          type: "about:blank",
          title: "Internal Server Error",
          status: 500,
          code: "internal_error",
          request_id: "e2e-ref-500",
        }),
      }),
    );

    await submitReading(page, "140", 0);
    await expect(page.getByText("Reading saved")).toBeVisible();
    const notice = page.getByRole("alert").filter({ hasText: "Out of date" });
    await expect(notice).toContainText("e2e-ref-500");
    await expect(page.getByText(/^As of /)).toBeVisible();
    await expect(intervals(page).locator('tr[data-kind="step"]')).toHaveCount(1);

    await submitReading(page, "150", 0).catch(() => undefined);
    await expect(page.getByLabel("Meter value")).toBeEnabled();

    await page.unroute(pattern);
    await notice.getByRole("button", { name: "Retry" }).click();
    await expect(notice).toHaveCount(0);
    await expect(intervals(page).locator('tr[data-kind="step"]')).toHaveCount(2);
  });

  test("J9 a lost session sends the next browser call to login once, then back", async ({
    page,
    context,
  }) => {
    const { meterId } = await createMeter(page, [
      [20, "100"],
      [10, "120"],
    ]);
    const { email } = JSON.parse(readFileSync(SHARED_INFO, "utf8")) as { email: string };
    const url = `/meters/${meterId}`;
    await page.goto(url);
    await waitForPlot(page);

    await context.clearCookies();
    const logins: string[] = [];
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.url().includes("/login")) {
        logins.push(request.url());
      }
    });
    await submitReading(page, "140", 0);
    await expect(page).toHaveURL(/\/login\?next=/);
    expect(new URL(page.url()).searchParams.get("next")).toBe(url);
    expect(logins).toHaveLength(1);

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(new RegExp(`${url}$`));
    await expect(page.getByRole("heading", { name: "Add a reading" })).toBeVisible();

    // Later tests reuse the file, not this context, so nothing leaks from here.
  });
});

test.describe("J8 cross user", () => {
  test("another account sees the not found page, the same as an unknown id", async ({
    browser,
  }) => {
    const shared = await browser.newContext({ storageState: SHARED_STATE });
    const sharedPage = await shared.newPage();
    const baseURL = test.info().project.use.baseURL as string;
    await sharedPage.goto(`${baseURL}/`);
    const made = await createMeter(sharedPage, [[5, "10"]]);
    await shared.close();

    const pristine = await browser.newContext({ storageState: PRISTINE_STATE, baseURL });
    const page = await pristine.newPage();
    const paths = [
      `/meters/${made.meterId}`,
      `/properties/${made.propertyId}`,
      "/meters/00000000-0000-4000-8000-000000000000",
      "/properties/00000000-0000-4000-8000-000000000000",
      "/meters/not-a-uuid",
    ];
    for (const target of paths) {
      await page.goto(target);
      await expect(
        page.getByRole("heading", { name: "We couldn't find that page." }),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "Go to your properties" })).toBeVisible();
      await expect(page.getByText(made.nickname)).toHaveCount(0);
    }
    await pristine.close();
  });
});

test.describe("J10 demo", () => {
  test("the seed runs twice and shows one demo property with its stories", async ({ page }) => {
    const repo = path.resolve(__dirname, "..", "..");
    const seed = () =>
      execFileSync(
        "uv",
        ["run", "python", "backend/scripts/seed_demo.py", "--api-url", API_ORIGIN],
        {
          cwd: repo,
          encoding: "utf8",
          shell: process.platform === "win32",
          env: { ...process.env, ENERGYIQ_ENV: "test" },
        },
      );
    seed();
    const output = seed();
    expect(output).toContain("demo@example.test");

    await page.goto("/login");
    await page.getByLabel("Email").fill("demo@example.test");
    await page.getByLabel("Password").fill("energyiq-demo-local-only");
    await page.getByRole("button", { name: "Sign in" }).click();

    const list = page.getByRole("list", { name: "Your properties" });
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await list.getByRole("link", { name: /Demo home/ }).click();
    await page.getByRole("link", { name: /Main meter/ }).click();
    await expect(page.getByRole("heading", { name: "Main meter", level: 1 })).toBeVisible();

    await page.goto(`${new URL(page.url()).pathname}?range=365d`);
    await waitForPlot(page);
    await expectStepDrawn(page);
    await expect(chart(page).locator(".chart-band").first()).toBeVisible();
    await expect(chart(page).locator(".chart-band--invalid")).toHaveCount(1);
    await expect(intervals(page)).toContainText(
      "The reading dropped with no recorded reset or replacement",
    );
    await expect(intervals(page)).toContainText("Before your first reading.");
    await expect(intervals(page)).toContainText("Average over 42 days");
    await expect(page.getByLabel("Meter value")).toBeVisible();
    expect(daysAgo(0)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

test.describe("signed in, reusing nothing else", () => {
  test.use({ storageState: SHARED_STATE });

  test("creating a property then going back shows the new row", async ({ page }) => {
    await page.goto("/");
    const nickname = uniqueName("Back");
    await page.getByLabel("Nickname").fill(nickname);
    await page.getByRole("button", { name: "Add property" }).click();
    await expect(page.getByRole("heading", { name: nickname, level: 1 })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("link", { name: new RegExp(nickname) })).toBeVisible();
  });

  test("the reading the warning links to can be reached", async ({ page }) => {
    const { meterId } = await createMeter(page);
    await addReading(page, meterId, 10, "900");
    await page.goto(`/meters/${meterId}`);
    await submitReading(page, "800", 0);
    await page.getByRole("link", { name: /900 kWh on/ }).click();
    await expect(page.locator('li[id^="reading-"]').first()).toBeFocused();
  });
});
