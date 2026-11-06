import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import type { Distributor, DraftCreate, InvoiceOut, RevisionOut } from "@/lib/api/generated/model";
import { compareDecimal, parseDecimal } from "@/lib/decimal";

export type Values = {
  period_start: string;
  period_end: string;
  billed_kwh: string;
  total_dop: string;
  energy_charge_dop: string;
  issue_date: string;
  due_date: string;
};
export const blank: Values = {
  period_start: "",
  period_end: "",
  billed_kwh: "",
  total_dop: "",
  energy_charge_dop: "",
  issue_date: "",
  due_date: "",
};
export const labels: Record<keyof Values, string> = {
  period_start: "Period start",
  period_end: "Period end",
  billed_kwh: "Billed use (kWh)",
  total_dop: "Invoice total (DOP)",
  energy_charge_dop: "Energy charge (DOP, optional)",
  issue_date: "Issue date (optional)",
  due_date: "Due date (optional)",
};
export const numericFields = new Set<keyof DraftCreate>([
  "billed_kwh",
  "total_dop",
  "energy_charge_dop",
]);
export const draftKeys = [
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
export function sameValue(
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

export const dateFields = new Set<keyof Values>([
  "period_start",
  "period_end",
  "issue_date",
  "due_date",
]);

export function fromRevision(row: RevisionOut): Values {
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

export function body(values: Values, distributor: Distributor): DraftCreate {
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
export function stateOf(invoice: InvoiceOut, revision: RevisionOut): string {
  if (revision.id === invoice.current_revision_id) return "current";
  if (revision.status === "confirmed") return "earlier confirmed";
  return revision.id === invoice.revisions.at(-1)!.id ? "open draft" : "superseded draft";
}

export const noChange = "Change at least one value before saving.";

export function message(error: unknown): string {
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

export function Fields({
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
