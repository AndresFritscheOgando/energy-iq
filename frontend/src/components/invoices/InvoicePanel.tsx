"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import {
  confirmInvoice,
  correctInvoice,
  createInvoice,
  getListInvoicesQueryKey,
  listInvoices,
} from "@/lib/api/generated/invoices/invoices";
import type { Distributor, DraftCreate, InvoiceOut, RevisionOut } from "@/lib/api/generated/model";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { compareDecimal, parseDecimal } from "@/lib/decimal";
import { formatDateTime } from "@/lib/format";

type Values = {
  period_start: string;
  period_end: string;
  billed_kwh: string;
  total_dop: string;
  energy_charge_dop: string;
  issue_date: string;
  due_date: string;
};
const blank: Values = {
  period_start: "",
  period_end: "",
  billed_kwh: "",
  total_dop: "",
  energy_charge_dop: "",
  issue_date: "",
  due_date: "",
};
const labels: Record<keyof Values, string> = {
  period_start: "Period start",
  period_end: "Period end",
  billed_kwh: "Billed use (kWh)",
  total_dop: "Invoice total (DOP)",
  energy_charge_dop: "Energy charge (DOP, optional)",
  issue_date: "Issue date (optional)",
  due_date: "Due date (optional)",
};
const numericFields = new Set<keyof DraftCreate>(["billed_kwh", "total_dop", "energy_charge_dop"]);
const draftKeys = [
  "distributor",
  "period_start",
  "period_end",
  "billed_kwh",
  "total_dop",
  "energy_charge_dop",
  "issue_date",
  "due_date",
] as const satisfies readonly (keyof DraftCreate & keyof RevisionOut)[];

/** Equal values, so "100" and "100.000000" are not a change. */
function sameValue(
  name: keyof DraftCreate,
  next: string | null | undefined,
  prior: string | null | undefined,
): boolean {
  if (numericFields.has(name) && next && prior) {
    const a = parseDecimal(next);
    const b = parseDecimal(prior);
    if (a && b) return compareDecimal(a, b) === 0;
  }
  return (next ?? null) === (prior ?? null);
}

const dateFields = new Set<keyof Values>(["period_start", "period_end", "issue_date", "due_date"]);

function fromRevision(row: RevisionOut): Values {
  return {
    period_start: row.period_start ?? "",
    period_end: row.period_end ?? "",
    billed_kwh: row.billed_kwh ?? "",
    total_dop: row.total_dop ?? "",
    energy_charge_dop: row.energy_charge_dop ?? "",
    issue_date: row.issue_date ?? "",
    due_date: row.due_date ?? "",
  };
}

function body(values: Values, distributor: Distributor): DraftCreate {
  return {
    distributor,
    period_start: values.period_start || null,
    period_end: values.period_end || null,
    billed_kwh: values.billed_kwh || null,
    total_dop: values.total_dop || null,
    energy_charge_dop: values.energy_charge_dop || null,
    issue_date: values.issue_date || null,
    due_date: values.due_date || null,
  };
}

/** What a revision is now, since a stored draft or confirmed status never changes. */
function stateOf(invoice: InvoiceOut, revision: RevisionOut): string {
  if (revision.id === invoice.current_revision_id) return "current";
  if (revision.status === "confirmed") return "earlier confirmed";
  return revision.id === invoice.revisions.at(-1)!.id ? "open draft" : "superseded draft";
}

const noChange = "Change at least one value before saving.";

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "invoice_period_overlap")
      return "This meter already has a confirmed invoice for those dates.";
    if (error.code === "meter_inactive")
      return "This meter is inactive, so invoices can no longer be changed.";
    if (error.code === "stale_invoice_revision")
      return "This invoice changed since you opened it. The form now shows the latest values, so review them and enter your change again.";
    if (error.code === "invoice_incomplete")
      return "Complete the required values before confirming.";
    if (error.code === "distributor_discrepancy")
      return "The invoice distributor differs from this meter. Review it before confirmation.";
    if (error.code === "empty_correction") return noChange;
    if (error.status === 422) return "Check the dates and decimal values, then try again.";
    if (error.status === 404) return "This invoice or meter is no longer available.";
  }
  if (error instanceof Error && error.message === noChange) return error.message;
  return "The invoice could not be saved. Try again.";
}

function Fields({
  values,
  onChange,
  prefix,
}: {
  values: Values;
  onChange: (value: Values) => void;
  prefix: string;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {(Object.keys(labels) as (keyof Values)[]).map((name) => (
        <label key={name} className="flex flex-col gap-1 text-sm font-medium">
          <span>{labels[name]}</span>
          <Input
            name={`${prefix}-${name}`}
            type={dateFields.has(name) ? "date" : "text"}
            inputMode={dateFields.has(name) ? undefined : "decimal"}
            value={values[name]}
            onChange={(event) => onChange({ ...values, [name]: event.target.value })}
            autoComplete="off"
          />
        </label>
      ))}
    </div>
  );
}

export function InvoicePanel({
  meterId,
  distributor,
  zone,
  active = true,
}: {
  meterId: string;
  distributor: Distributor;
  zone: string;
  /** An inactive meter keeps its invoices readable but takes no new writes. */
  active?: boolean;
}) {
  const queryClient = useQueryClient();
  const key = useIdempotencyKey();
  const list = useInfiniteQuery({
    queryKey: getListInvoicesQueryKey(meterId),
    queryFn: ({ pageParam }) =>
      listInvoices(meterId, { limit: 100, cursor: pageParam ?? undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const invoices = list.data?.pages.flatMap((page) => page.items) ?? [];
  const [values, setValues] = useState(blank);
  // The revision the owner was looking at when the form opened; the API rejects it if stale.
  const [editing, setEditing] = useState<{ invoiceId: string; baseId: string } | null>(null);
  const [editValues, setEditValues] = useState(blank);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: async (
      work:
        | { kind: "create"; data: DraftCreate }
        | { kind: "confirm"; invoice: InvoiceOut; draft: RevisionOut }
        | { kind: "correct"; invoice: InvoiceOut; baseId: string; data: DraftCreate },
    ) => {
      const retryKey = key.keyFor(JSON.stringify(work));
      const options = { headers: { "Idempotency-Key": retryKey } };
      if (work.kind === "create") return createInvoice(meterId, work.data, options);
      if (work.kind === "confirm")
        return confirmInvoice(
          work.invoice.id,
          {
            draft_revision_id: work.draft.id,
            expected_current_revision_id: work.invoice.current_revision_id,
          },
          options,
        );
      const base = work.invoice.revisions.find((row) => row.id === work.baseId)!;
      const changed = Object.fromEntries(
        draftKeys
          .filter((name) => !sameValue(name, work.data[name], base[name]))
          .map((name) => [name, work.data[name]]),
      );
      if (Object.keys(changed).length === 0) throw new Error(noChange);
      return correctInvoice(
        work.invoice.id,
        {
          base_revision_id: base.id,
          expected_current_revision_id: work.invoice.current_revision_id,
          ...changed,
        },
        options,
      );
    },
    onSuccess: () => {
      key.reset();
      setProblem(null);
      void queryClient.invalidateQueries({ queryKey: getListInvoicesQueryKey(meterId) });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void queryClient.invalidateQueries({ queryKey: getListInvoicesQueryKey(meterId) });
    },
  });

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    setNotice(null);
    try {
      await mutation.mutateAsync({ kind: "create", data: body(values, distributor) });
      setValues(blank);
      setNotice("Draft saved. Review the values, then confirm it.");
    } catch (error) {
      setProblem(message(error));
    }
  }

  async function confirm(invoice: InvoiceOut, draft: RevisionOut) {
    setProblem(null);
    setNotice(null);
    try {
      await mutation.mutateAsync({ kind: "confirm", invoice, draft });
      setNotice("Invoice confirmed.");
    } catch (error) {
      setProblem(message(error));
    }
  }

  async function correct(event: FormEvent<HTMLFormElement>, invoice: InvoiceOut, baseId: string) {
    event.preventDefault();
    setProblem(null);
    setNotice(null);
    try {
      await mutation.mutateAsync({
        kind: "correct",
        invoice,
        baseId,
        data: body(editValues, distributor),
      });
      setEditing(null);
      setNotice(
        invoice.revisions.find((row) => row.id === baseId)!.status === "draft" &&
          !invoice.current_revision_id
          ? "Draft updated. Review the values, then confirm it."
          : "Correction saved as a draft. Review and confirm it.",
      );
    } catch (error) {
      setProblem(message(error));
      if (error instanceof ApiError && error.code === "stale_invoice_revision") {
        // Reopen on the newest revision so the next save is not stale again.
        const fresh = (await list.refetch()).data?.pages
          .flatMap((page) => page.items)
          .find((item) => item.id === invoice.id);
        const latest = fresh?.revisions.at(-1);
        if (latest) {
          setEditing({ invoiceId: invoice.id, baseId: latest.id });
          setEditValues(fromRevision(latest));
        } else {
          setEditing(null);
        }
      }
    }
  }

  return (
    <section aria-labelledby="invoices-title" className="rounded-lg border bg-card p-5 space-y-5">
      <div>
        <h2 id="invoices-title" className="text-lg font-semibold">
          Invoices
        </h2>
        <p className="text-sm text-muted-foreground">
          Record what the bill says. Values are saved as a draft until you confirm them.
        </p>
      </div>
      {problem && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {problem}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md border p-3 text-sm">
          {notice}
        </p>
      )}
      {!active && (
        <p className="rounded-md border bg-muted p-3 text-sm">
          This meter is inactive. Its invoices stay available to read, but they cannot be changed.
        </p>
      )}
      {active && (
        <form onSubmit={(event) => void save(event)} className="space-y-3 border-b pb-5">
          <h3 className="font-medium">New manual invoice</h3>
          <p className="text-sm text-muted-foreground">
            Distributor: {distributor}. Enter dates as printed on the bill, including both the first
            and last day. You can save with values missing and finish the draft later; confirming
            needs the period, billed use, and total.
          </p>
          <Fields values={values} onChange={setValues} prefix="new-invoice" />
          <Button type="submit" disabled={mutation.isPending}>
            Save draft
          </Button>
        </form>
      )}
      {list.isPending && <p role="status">Loading invoices…</p>}
      {list.isError && (
        <div role="alert" className="text-sm">
          Invoices could not load.{" "}
          <Button type="button" variant="outline" onClick={() => void list.refetch()}>
            Retry
          </Button>
        </div>
      )}
      {list.data && invoices.length === 0 && (
        <p className="text-sm text-muted-foreground">No invoices have been saved for this meter.</p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {invoices.map((invoice) => {
          const latest = invoice.revisions.at(-1)!;
          return (
            <article key={invoice.id} className="space-y-3 rounded-lg border p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">
                    {latest.period_start ?? "Period needed"} to{" "}
                    {latest.period_end ?? "Period needed"}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {latest.billed_kwh ?? "Use needed"} kWh · DOP{" "}
                    {latest.total_dop ?? "Total needed"}
                  </p>
                </div>
                <span className="rounded-full bg-muted px-2 py-1 text-xs">
                  {latest.status === "draft" ? "Draft" : "Confirmed"}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Revision {latest.revision_number}. Recorded by you at{" "}
                {formatDateTime(latest.created_at, "dateTime", zone) ?? latest.created_at}.{" "}
                {latest.confirmed_at
                  ? `Confirmed ${formatDateTime(latest.confirmed_at, "dateTime", zone) ?? latest.confirmed_at}.`
                  : "Waiting for your confirmation."}
              </p>
              {latest.status === "draft" && invoice.current_revision_id && (
                <p className="text-xs text-muted-foreground">
                  The earlier confirmed revision stays current until you confirm this draft.
                </p>
              )}
              <details className="text-sm" open={latest.status === "draft"}>
                <summary className="cursor-pointer underline underline-offset-4">
                  Review all values and sources
                </summary>
                <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                  {(["distributor", ...Object.keys(labels)] as (keyof RevisionOut)[]).map(
                    (name) => (
                      <div key={name}>
                        <dt className="font-medium">
                          {name === "distributor" ? "Distributor" : labels[name as keyof Values]}
                        </dt>
                        <dd>
                          {String(latest[name] ?? "Missing")} (
                          {latest.field_origins[name] ?? "no source"})
                        </dd>
                      </div>
                    ),
                  )}
                </dl>
              </details>
              {active && latest.status === "draft" && (
                <Button
                  type="button"
                  disabled={mutation.isPending}
                  onClick={() => void confirm(invoice, latest)}
                >
                  Confirm revision
                </Button>
              )}
              {active && editing?.invoiceId !== invoice.id && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setEditing({ invoiceId: invoice.id, baseId: latest.id });
                    setEditValues(fromRevision(latest));
                  }}
                >
                  {latest.status === "confirmed" ? "Correct values" : "Edit draft"}
                </Button>
              )}
              {active && editing?.invoiceId === invoice.id && (
                <form
                  onSubmit={(event) => void correct(event, invoice, editing.baseId)}
                  className="space-y-3"
                >
                  <h4 className="font-medium">
                    {latest.status === "confirmed" ? "Correction draft" : "Edit draft"}
                  </h4>
                  <Fields
                    values={editValues}
                    onChange={setEditValues}
                    prefix={`correction-${invoice.id}`}
                  />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={mutation.isPending}>
                      {latest.status === "confirmed" ? "Save correction" : "Save draft changes"}
                    </Button>
                    <Button type="button" variant="outline" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
              {invoice.revisions.length > 1 && (
                <details className="text-sm">
                  <summary className="cursor-pointer underline underline-offset-4">
                    Revision history
                  </summary>
                  <ol className="mt-2 space-y-2">
                    {invoice.revisions.map((revision) => (
                      <li key={revision.id}>
                        Revision {revision.revision_number}, {stateOf(invoice, revision)}, DOP{" "}
                        {revision.total_dop ?? "missing"}. Changed:{" "}
                        {revision.changed_fields.join(", ") || "none"}. Earlier values:{" "}
                        {Object.entries(revision.old_values)
                          .map(([name, value]) => `${name} ${value ?? "empty"}`)
                          .join(", ") || "none"}
                        .
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </article>
          );
        })}
      </div>
      {list.hasNextPage && (
        <Button
          type="button"
          variant="outline"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          {list.isFetchingNextPage ? "Loading…" : "Load more invoices"}
        </Button>
      )}
    </section>
  );
}
