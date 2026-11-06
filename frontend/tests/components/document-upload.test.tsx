/** PDF upload form (spec 0012/0005 AC-1): multipart body, status polling, errors. */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { DocumentUpload } from "@/components/documents/DocumentUpload";
import { en } from "@/messages/en";

import { problem } from "../msw/problems";
import { server } from "../msw/server";
import { axeViolations, renderWithClient } from "./render";

const METER = "00000000-0000-4000-8000-0000000000b1";
const UPLOAD = `*/api/v1/meters/${METER}/documents`;
const DOC_ID = "00000000-0000-4000-8000-0000000000d1";

function doc(state: string, runState: string) {
  return {
    id: DOC_ID,
    meter_id: METER,
    state,
    reason_code: null,
    size_bytes: 2048,
    sha256: "ab".repeat(32),
    created_at: "2026-11-05T15:00:00Z",
    deleted_at: null,
    run: {
      id: "00000000-0000-4000-8000-0000000000e1",
      run_number: 1,
      state: runState,
      attempts: 0,
      error_code: null,
      created_at: "2026-11-05T15:00:00Z",
      started_at: null,
      finished_at: null,
    },
  };
}

const pdf = () => new File(["%PDF-1.4\n%%EOF"], "bill.pdf", { type: "application/pdf" });

describe("DocumentUpload", () => {
  it("has no axe violations", async () => {
    const { container } = renderWithClient(<DocumentUpload meterId={METER} active />);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("asks for a file before calling the API", async () => {
    let called = false;
    server.use(
      http.post(UPLOAD, () => {
        called = true;
        return HttpResponse.json(doc("uploaded", "queued"), { status: 201 });
      }),
    );
    renderWithClient(<DocumentUpload meterId={METER} active />);
    await userEvent.setup().click(screen.getByRole("button", { name: en.documents.submit }));
    expect(screen.getByRole("alert").textContent).toBe(en.documents.noFile);
    expect(called).toBe(false);
  });

  it("sends multipart with CSRF and an idempotency key, then follows the run to review", async () => {
    let seen: Request | null = null;
    let polls = 0;
    server.use(
      http.post(UPLOAD, ({ request }) => {
        seen = request.clone();
        return HttpResponse.json(doc("uploaded", "queued"), { status: 201 });
      }),
      http.get(`*/api/v1/documents/${DOC_ID}`, () => {
        polls += 1;
        return HttpResponse.json(doc("needs_review", "succeeded"));
      }),
    );
    renderWithClient(<DocumentUpload meterId={METER} active />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText(en.documents.fileLabel), pdf());
    await user.click(screen.getByRole("button", { name: en.documents.submit }));

    await screen.findByText(en.documents.state.needs_review, undefined, { timeout: 4000 });
    expect(seen!.headers.get("Content-Type")).toMatch(/^multipart\/form-data; boundary=/);
    expect(seen!.headers.get("X-EnergyIQ-CSRF")).toBe("1");
    expect(seen!.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(polls).toBeGreaterThan(0);
  });

  it.each([
    [413, "upload_too_large", en.documents.tooLarge],
    [415, "upload_not_pdf", en.documents.notPdf],
    [422, "pdf_invalid", en.documents.invalid],
    [429, "too_many_active", en.documents.tooMany],
  ])("maps %i %s to plain wording", async (status, code, text) => {
    server.use(http.post(UPLOAD, () => problem(status, code)));
    renderWithClient(<DocumentUpload meterId={METER} active />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText(en.documents.fileLabel), pdf());
    await user.click(screen.getByRole("button", { name: en.documents.submit }));
    expect((await screen.findByRole("alert")).textContent).toBe(text);
  });

  it("offers no upload on an inactive meter", () => {
    renderWithClient(<DocumentUpload meterId={METER} active={false} />);
    expect(screen.queryByRole("button", { name: en.documents.submit })).toBeNull();
    expect(screen.getByText(en.documents.inactive)).toBeTruthy();
  });
});
