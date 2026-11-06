/**
 * Registers the two reusable accounts (spec 0011 child 0003 AC-4). All browsers
 * share one rate limit bucket here (5 registers an hour), so the suite registers
 * exactly four accounts and reuses signed in state.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { test } from "@playwright/test";

import {
  PASSWORD,
  PRISTINE_STATE,
  SHARED_INFO,
  SHARED_STATE,
  expect,
  uniqueEmail,
} from "./support";

async function register(page: import("@playwright/test").Page, email: string, state: string) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your properties" })).toBeVisible();
  await page.context().storageState({ path: state });
}

test("register the shared account", async ({ page }) => {
  mkdirSync(path.dirname(SHARED_STATE), { recursive: true });
  const email = uniqueEmail("shared");
  await register(page, email, SHARED_STATE);
  writeFileSync(SHARED_INFO, JSON.stringify({ email }));
});

test("register the pristine account", async ({ page }) => {
  await register(page, uniqueEmail("pristine"), PRISTINE_STATE);
});
