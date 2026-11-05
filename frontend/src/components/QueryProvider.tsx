"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createBrowserQueryClient } from "@/lib/api/query-client";

/** The browser's single QueryClient, created once per page load. */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createBrowserQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
