"use client";

/**
 * Review what the reader found in an uploaded bill (spec 0012/0005 AC-2, AC-3).
 *
 * Every proposed value sits beside its page and quoted text, with wording for
 * anything the server flagged. The owner edits the value to save; saving makes
 * a draft only. Confirmation stays a separate action in the invoice list, and
 * nothing here computes a value: proposals come from the API as sent.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import {
  getListExtractionsQueryKey,
  listExtractions,
} from "@/lib/api/generated/documents/documents";
import { createInvoice, getListInvoicesQueryKey } from "@/lib/api/generated/invoices/invoices";
import type {
  Distributor,
  DraftCreate,
  ExtractionOut,
  ProposedFieldOut,
} from "@/lib/api/generated/model";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { compareDecimal, parseDecimal } from "@/lib/decimal";
import { en } from "@/messages/en";

const t = en.review;

const FIELDS = [
  "period_start",
  "period_end",
  "billed_kwh",
  "total_dop",
  "energy_charge_dop",
  "issue_date",
  "due_date",
] as const;
type FieldName = (typeof FIELDS)[number];

const LABELS: Record<FieldName | "distributor", string> = {
  distributor: "Distributor",
  period_start: "Period start",
  period_end: "Period end",
  billed_kwh: "Billed use (kWh)",
  total_dop: "Invoice total (DOP)",
  energy_charge_dop: "Energy charge (DOP)",
  issue_date: "Issue date",
  due_date: "Due date",
};
const DATE_FIELDS = new Set<FieldName>(["period_start", "period_end", "issue_date", "due_date"]);
const NUMBER_FIELDS = new Set<FieldName>(["billed_kwh", "total_dop", "energy_charge_dop"]);

function labelOf(name: string): string {
  return name in LABELS ? LABELS[name as keyof typeof LABELS] : name;
}

function issueText(code: string): string {
  const known = t.issue as Record<string, string>;
  return known[code] ?? t.issueOther;
}

function conflictText(code: string, names: string): string {
  const known = t.conflict as Record<string, (names: string) => string>;
  return (known[code] ?? t.conflictOther)(names);
}

/** A proposed value the form may start from. A contradicted field starts blank. */
function startValue(field: ProposedFieldOut | undefined): string {
  if (!field || field.state === "not_found" || field.value === null) return "";
  return field.issues.includes("contradiction") ? "" : field.value;
}

function sameValue(name: FieldName, next: string, proposed: string | null): boolean {
  if (!next || proposed === null) return false;
  if (NUMBER_FIELDS.has(name)) {
    const a = parseDecimal(next);
    const b = parseDecimal(proposed);
    return a !== null && b !== null && compareDecimal(a, b) === 0;
  }
  return next === proposed;
}

function saveMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "origin_mismatch") return t.saveMismatch;
    if (error.code === "meter_inactive") return t.saveInactive;
    if (error.status === 404) return t.saveGone;
    if (error.status === 422) return t.saveInvalid;
  }
  return t.saveFailed;
}

function ReviewForm({
  extraction,
  documentId,
  meterId,
  distributor,
}: {
  extraction: ExtractionOut;
  documentId: string;
  meterId: string;
  distributor: Distributor;
}) {
  const queryClient = useQueryClient();
  const key = useIdempotencyKey();
  const byName = new Map(extraction.proposal.fields.map((field) => [field.name, field]));
  const [values, setValues] = useState<Record<FieldName, string>>(
    () => Object.fromEntries(FIELDS.map((name) => [name, startValue(byName.get(name))])) as never,
  );
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: (data: DraftCreate) =>
      createInvoice(meterId, data, {
        headers: { "Idempotency-Key": key.keyFor(JSON.stringify(data)) },
      }),
    onSuccess: () => {
      key.reset();
      void queryClient.invalidateQueries({ queryKey: getListInvoicesQueryKey(meterId) });
    },
  });

  const proposedDistributor = byName.get("distributor");
  const found =
    proposedDistributor && proposedDistributor.state !== "not_found"
      ? proposedDistributor.value
      : null;
  const tariff = byName.get("tariff_class");
  const tariffValue = tariff && tariff.state !== "not_found" ? tariff.value : null;
  const contradictions = new Map(extraction.proposal.contradictions.map((c) => [c.field, c]));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    const origins: Record<string, "manual" | "document"> = {};
    const data: DraftCreate = { source_document_id: documentId, distributor };
    for (const name of FIELDS) {
      const value = values[name].trim();
      data[name] = value || null;
      if (!value) continue;
      const field = byName.get(name);
      const kept =
        field !== undefined &&
        field.state !== "not_found" &&
        !field.issues.includes("contradiction") &&
        sameValue(name, value, field.value);
      origins[name] = kept ? "document" : "manual";
    }
    origins.distributor = found === distributor ? "document" : "manual";
    data.field_origins = origins;
    try {
      await save.mutateAsync(data);
      setSaved(true);
    } catch (error) {
      setProblem(saveMessage(error));
    }
  }

  if (saved) {
    return (
      <p role="status" className="rounded-md border p-3 text-sm">
        {t.saved}
      </p>
    );
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <p className="text-sm text-muted-foreground">{t.intro}</p>
      <p className="text-xs text-muted-foreground">{t.readBy(extraction.model)}</p>
      {extraction.proposal.conflicts.length > 0 && (
        <div
          className="rounded-md border border-destructive p-3 text-sm"
          role="group"
          aria-labelledby="conflicts-title"
        >
          <h4 id="conflicts-title" className="font-medium">
            {t.conflictsTitle}
          </h4>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {extraction.proposal.conflicts.map((conflict, index) => (
              <li key={`${conflict.code}-${index}`}>
                {conflictText(conflict.code, conflict.fields.map(labelOf).join(" and "))}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="rounded-md border p-3 text-sm">
        <p className="font-medium">{LABELS.distributor}</p>
        <p className="text-muted-foreground">
          {found === null
            ? t.notFound
            : found === distributor
              ? t.distributorSame(found)
              : t.distributorOther(found, distributor)}
        </p>
        {tariffValue !== null && (
          <p className="text-muted-foreground">{t.tariffClass(tariffValue)}</p>
        )}
      </div>
      <ul className="grid gap-3 lg:grid-cols-2">
        {FIELDS.map((name) => {
          const field = byName.get(name);
          const candidates = contradictions.get(name)?.candidates ?? [];
          const inputId = `proposal-${name}`;
          const noteId = `${inputId}-note`;
          return (
            <li key={name} className="space-y-2 rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h5 className="font-medium">{LABELS[name]}</h5>
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
                  {t.state[field?.state ?? "not_found"]}
                </span>
              </div>
              <div id={noteId} className="space-y-1 text-muted-foreground">
                <p>
                  {t.proposed}:{" "}
                  <span className="font-medium text-foreground">{field?.value ?? t.notFound}</span>
                </p>
                {field?.quote ? (
                  <p>
                    {field.page_number !== null && `${t.page(field.page_number)}: `}
                    <q>{field.quote}</q>
                  </p>
                ) : (
                  field?.value && <p>{t.noEvidence}</p>
                )}
                {field?.quote && !field.evidence_verified && <p>{t.unverified}</p>}
                {field?.uncertainty && <p>{field.uncertainty}</p>}
                {field?.issues.map((code) => (
                  <p key={code}>{issueText(code)}</p>
                ))}
                {candidates.length > 0 && (
                  <div>
                    <p className="font-medium text-foreground">{t.candidatesTitle}</p>
                    <ul className="list-disc pl-5">
                      {candidates.map((candidate, index) => (
                        <li key={index}>
                          {candidate.value ?? candidate.raw_value ?? t.notFound}
                          {candidate.quote && (
                            <>
                              {" "}
                              (
                              {candidate.page_number !== null &&
                                `${t.page(candidate.page_number)}: `}
                              <q>{candidate.quote}</q>)
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <label className="flex flex-col gap-1 font-medium">
                <span>{t.edited(LABELS[name])}</span>
                <Input
                  id={inputId}
                  name={inputId}
                  type={DATE_FIELDS.has(name) ? "date" : "text"}
                  inputMode={DATE_FIELDS.has(name) ? undefined : "decimal"}
                  value={values[name]}
                  aria-describedby={noteId}
                  autoComplete="off"
                  onChange={(event) => setValues({ ...values, [name]: event.target.value })}
                />
              </label>
            </li>
          );
        })}
      </ul>
      {problem && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {problem}
        </p>
      )}
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? t.saving : t.save}
      </Button>
    </form>
  );
}

export function ProposalReview({
  documentId,
  meterId,
  distributor,
}: {
  documentId: string;
  meterId: string;
  distributor: Distributor;
}) {
  const query = useQuery({
    queryKey: getListExtractionsQueryKey(documentId),
    queryFn: () => listExtractions(documentId),
  });
  const newest = query.data?.items[0];
  return (
    <section aria-labelledby={`review-${documentId}`} className="space-y-3 rounded-lg border p-4">
      <h4 id={`review-${documentId}`} className="font-medium">
        {t.title}
      </h4>
      {query.isPending && <p role="status">{t.loading}</p>}
      {query.isError && (
        <div role="alert" className="text-sm">
          {t.loadFailed}{" "}
          <Button type="button" variant="outline" onClick={() => void query.refetch()}>
            {t.retry}
          </Button>
        </div>
      )}
      {query.data && !newest && <p className="text-sm">{t.nothing}</p>}
      {newest && (
        <ReviewForm
          key={newest.run_id}
          extraction={newest}
          documentId={documentId}
          meterId={meterId}
          distributor={distributor}
        />
      )}
    </section>
  );
}
