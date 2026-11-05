import { HttpResponse } from "msw";

/** A FastAPI style problem response (RFC 9457 with a stable `code`). */
export function problem(
  status: number,
  code: string,
  extra: Record<string, unknown> = {},
  headers: Record<string, string> = {},
) {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: "Problem",
      status,
      code,
      detail: "Server detail text that must never be shown.",
      request_id: "req-123",
      ...extra,
    },
    {
      status,
      headers: { "Content-Type": "application/problem+json", ...headers },
    },
  );
}

export const USER = {
  id: "00000000-0000-4000-8000-0000000000aa",
  email: "owner@example.test",
  created_at: "2026-11-05T02:30:00Z",
};
