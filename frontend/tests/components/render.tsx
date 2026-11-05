import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { vi } from "vitest";

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const clear = vi.spyOn(client, "clear");
  return {
    client,
    clear,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

/** axe-core violations, as `id: help` lines so a failure is readable. */
export async function axeViolations(container: Element): Promise<string[]> {
  const results = await axe.run(container, {
    // jsdom cannot compute colors; contrast is checked in the browser pass.
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.map((violation) => `${violation.id}: ${violation.help}`);
}
