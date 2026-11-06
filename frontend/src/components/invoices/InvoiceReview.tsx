"use client";

/**
 * The invoice review screen (spec 0012/0005 AC-2 to AC-4).
 *
 * Source evidence sits beside the editable values. Saving writes a draft
 * revision; confirming is a separate action that sends the draft revision ID
 * and the current revision the owner saw. A stale answer keeps every edit on
 * screen and waits for the owner to choose; nothing is retried silently.
 * No value is computed here, and the PDF is only ever a download.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { conflictText, issueText } from "@/components/documents/ProposalReview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import {
  getDownloadSourceUrl,
  getListExtractionsQueryKey,
  listExtractions,
  useGetDocument,
} from "@/lib/api/generated/documents/documents";
import {
  confirmInvoice,
  correctInvoice,
  getGetInvoiceQueryKey,
  getInvoice,
  getListInvoicesQueryKey,
  useGetInvoice,
} from "@/lib/api/generated/invoices/invoices";
import { useGetMeter } from "@/lib/api/generated/meters/meters";
import type {
  ContradictionOut,
  InvoiceOut,
  ProposedFieldOut,
  RevisionOut,
} from "@/lib/api/generated/model";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { formatDateTime } from "@/lib/format";
import { en } from "@/messages/en";

import {
  dateFields,
  fromRevision,
  labels,
  noChange,
  sameValue,
  stateOf,
  type Values,
} from "./invoice-shared";

const t = en.invoiceScreens;
const r = en.review;
const FIELD_NAMES = Object.keys(labels) as (keyof Values)[];
const REQUIRED = ["period_start", "period_end", "billed_kwh", "total_dop"] as const;

const PLAIN: Record<keyof Values, string> = {
  period_start: "Period start",
  period_end: "Period end",
  billed_kwh: "Billed use (kWh)",
  total_dop: "Invoice total (DOP)",
  energy_charge_dop: "Energy charge (DOP)",
  issue_date: "Issue date",
  due_date: "Due date",
};

function labelOf(name: string): string {
  return name === "distributor"
    ? t.distributorLabel
    : ((PLAIN as Record<string, string>)[name] ?? name);
}

/** Why a saved revision cannot be confirmed, by field. Mirrors the server; never invents a value. */
export function confirmProblems(revision: RevisionOut, meterDistributor: string | null): string[] {
  const found: string[] = [];
  if (revision.distributor === null) found.push(t.missingValue(t.distributorLabel));
  else if (meterDistributor && revision.distributor !== meterDistributor)
    found.push(t.distributorMismatch(revision.distributor, meterDistributor));
  for (const name of REQUIRED) {
    if (revision[name] === null) found.push(t.missingValue(PLAIN[name]));
    else if (!(name in revision.field_origins)) found.push(t.missingSource(PLAIN[name]));
  }
  if (revision.period_start && revision.period_end && revision.period_start > revision.period_end)
    found.push(t.periodInverted);
  return found;
}

function failure(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.code === "invoice_period_overlap") return t.overlap;
    if (error.code === "meter_inactive") return t.inactiveError;
    if (error.code === "distributor_discrepancy") return t.distributorError;
    if (error.code === "invoice_incomplete") return t.incompleteError;
    if (error.code === "empty_correction") return t.noChange;
    if (error.status === 422) return t.invalid;
    if (error.status === 404) return t.gone;
  }
  if (error instanceof Error && error.message === noChange) return t.noChange;
  return fallback;
}

function isStale(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 409 && error.code === "stale_invoice_revision"
  );
}

function Evidence({
  name,
  revision,
  proposed,
  contradiction,
  hasProposal,
}: {
  name: keyof Values;
  revision: RevisionOut;
  proposed: ProposedFieldOut | undefined;
  contradiction: ContradictionOut | undefined;
  hasProposal: boolean;
}) {
  const origin = revision.field_origins[name];
  const originText =
    origin === "document"
      ? t.origin.document
      : origin === "manual"
        ? t.origin.manual
        : t.origin.none;
  return (
    <div className="space-y-1 text-muted-foreground">
      <p>
        <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{originText}</span>
      </p>
      {hasProposal && proposed && proposed.state !== "not_found" ? (
        <>
          <p>
            {t.proposed}:{" "}
            <span className="font-medium text-foreground">{proposed.value ?? t.notFound}</span> (
            {r.state[proposed.state]})
          </p>
          {proposed.quote ? (
            <p>
              {proposed.page_number !== null && `${r.page(proposed.page_number)}: `}
              <q>{proposed.quote}</q>
            </p>
          ) : (
            <p>{r.noEvidence}</p>
          )}
          {proposed.quote && !proposed.evidence_verified && <p>{r.unverified}</p>}
          {proposed.uncertainty && <p>{proposed.uncertainty}</p>}
        </>
      ) : (
        <p>{t.noEvidenceForField}</p>
      )}
      {hasProposal && proposed?.issues.map((code) => <p key={code}>{issueText(code)}</p>)}
      {contradiction && contradiction.candidates.length > 0 && (
        <div>
          <p className="font-medium text-foreground">{r.candidatesTitle}</p>
          <ul className="list-disc pl-5">
            {contradiction.candidates.map((candidate, index) => (
              <li key={index}>
                {candidate.value ?? candidate.raw_value ?? r.notFound}
                {candidate.quote && (
                  <>
                    {" "}
                    ({candidate.page_number !== null && `${r.page(candidate.page_number)}: `}
                    <q>{candidate.quote}</q>)
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SourcePanel({ documentId }: { documentId: string | null }) {
  const doc = useGetDocument(documentId ?? "", { query: { enabled: documentId !== null } });
  if (documentId === null) return <p className="text-sm">{t.sourceNone}</p>;
  if (doc.isPending) return <p role="status">{t.sourceLoading}</p>;
  if (doc.isError)
    return (
      <p role="alert" className="text-sm">
        {t.sourceGone}
      </p>
    );
  return (
    <div className="space-y-2 text-sm">
      <p>{t.sourceStatus(doc.data.state)}</p>
      <p>
        <a
          className="underline underline-offset-4"
          href={getDownloadSourceUrl(documentId)}
          download
        >
          {t.sourceDownload}
        </a>
      </p>
      <p className="text-muted-foreground">{t.sourceDownloadNote}</p>
    </div>
  );
}

function sourceDocumentOf(invoice: InvoiceOut): string | null {
  let found: string | null = null;
  for (const row of invoice.revisions) found = row.source_document_id ?? found;
  return found;
}

function ReviewBody({ invoice, zone }: { invoice: InvoiceOut; zone: string }) {
  const queryClient = useQueryClient();
  const key = useIdempotencyKey();
  const { data: meter } = useGetMeter(invoice.meter_id);
  const active = meter?.active !== false;
  const latest = invoice.revisions.at(-1)!;
  const documentId = sourceDocumentOf(invoice);

  // What the owner opened: the revision to compare with, and the current one the API must still hold.
  const [baseId, setBaseId] = useState(latest.id);
  const [expected, setExpected] = useState(invoice.current_revision_id);
  const [values, setValues] = useState<Values>(() => fromRevision(latest));
  const [stale, setStale] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<string[]>([]);

  const base = invoice.revisions.find((row) => row.id === baseId) ?? latest;
  const changed = FIELD_NAMES.filter((name) => !sameValue(name, values[name] || null, base[name]));
  const dirty = changed.length > 0;

  const extractions = useQuery({
    queryKey: getListExtractionsQueryKey(documentId ?? ""),
    queryFn: () => listExtractions(documentId!),
    enabled: documentId !== null,
  });
  const newest = extractions.data?.items[0];
  const proposedByName = new Map(newest?.proposal.fields.map((field) => [field.name, field]));
  const contradictions = new Map(newest?.proposal.contradictions.map((c) => [c.field, c]));
  const conflicts = newest?.proposal.conflicts ?? [];

  function adopt(next: InvoiceOut, replaceValues: boolean) {
    setBaseId(next.revisions.at(-1)!.id);
    setExpected(next.current_revision_id);
    if (replaceValues) setValues(fromRevision(next.revisions.at(-1)!));
    queryClient.setQueryData(getGetInvoiceQueryKey(invoice.id), next);
    void queryClient.invalidateQueries({ queryKey: getListInvoicesQueryKey(invoice.meter_id) });
  }

  const save = useMutation({
    mutationFn: () => {
      const data: Record<string, string | null> = {};
      for (const name of changed) data[name] = values[name] || null;
      if (Object.keys(data).length === 0) throw new Error(noChange);
      return correctInvoice(
        invoice.id,
        { base_revision_id: base.id, expected_current_revision_id: expected, ...data },
        { headers: { "Idempotency-Key": key.keyFor(JSON.stringify(data) + base.id) } },
      );
    },
  });
  const confirm = useMutation({
    mutationFn: () =>
      confirmInvoice(
        invoice.id,
        { draft_revision_id: latest.id, expected_current_revision_id: expected },
        { headers: { "Idempotency-Key": key.keyFor(`confirm ${latest.id} ${expected}`) } },
      ),
  });

  /** A stale answer: keep the edits, say so, and wait for the owner to choose. */
  function markStale() {
    setStale(true);
    void queryClient.invalidateQueries({ queryKey: getGetInvoiceQueryKey(invoice.id) });
  }

  async function resolveStale(keepEdits: boolean) {
    setProblem(null);
    try {
      const fresh = await getInvoice(invoice.id);
      const latestRow = fresh.revisions.at(-1)!;
      adopt(fresh, !keepEdits);
      if (keepEdits) {
        // Keep only what the owner changed; every other field takes the newer saved value,
        // so a change made elsewhere is not overwritten by a stale copy.
        const theirs = fromRevision(latestRow);
        const mine = { ...theirs };
        for (const name of changed) mine[name] = values[name];
        setValues(mine);
      }
      setStale(false);
    } catch (error) {
      setProblem(failure(error, t.loadFailed));
    }
  }

  async function onSave() {
    setProblem(null);
    setNotice(null);
    setBlockers([]);
    try {
      const next = await save.mutateAsync();
      key.reset();
      adopt(next, true);
      setNotice(t.saved);
    } catch (error) {
      if (isStale(error)) markStale();
      else setProblem(failure(error, t.saveFailed));
    }
  }

  async function onConfirm() {
    setProblem(null);
    setNotice(null);
    if (dirty) {
      setProblem(t.unsavedEdits);
      return;
    }
    const found = confirmProblems(latest, meter?.distributor ?? null);
    setBlockers(found);
    if (found.length > 0) return;
    try {
      const next = await confirm.mutateAsync();
      key.reset();
      adopt(next, true);
      setNotice(t.confirmedDone);
    } catch (error) {
      if (isStale(error)) markStale();
      else setProblem(failure(error, t.confirmFailed));
    }
  }

  const busy = save.isPending || confirm.isPending;
  const when = (iso: string) => formatDateTime(iso, "dateTime", zone) ?? iso;
  const canConfirm = active && latest.status === "draft" && !stale;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full bg-muted px-2 py-1 text-xs">
          {latest.status === "draft" ? t.draft : t.confirmed}
        </span>
        <p className="text-xs text-muted-foreground">
          {latest.source_document_id ? t.sourceDocument : t.sourceManual}.{" "}
          {t.recorded(when(latest.created_at))}{" "}
          {latest.confirmed_at ? t.confirmedAt(when(latest.confirmed_at)) : t.awaiting}
        </p>
      </div>
      {!active && <p className="rounded-md border bg-muted p-3 text-sm">{t.inactive}</p>}
      <div aria-live="polite">
        {notice && (
          <p role="status" className="rounded-md border p-3 text-sm">
            {notice}
          </p>
        )}
      </div>
      {problem && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {problem}
        </p>
      )}
      {stale && (
        <div role="alert" className="space-y-2 rounded-md border border-destructive p-3 text-sm">
          <p>{t.stale}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => void resolveStale(true)}>
              {t.keepEdits}
            </Button>
            <Button type="button" variant="outline" onClick={() => void resolveStale(false)}>
              {t.useLatest}
            </Button>
          </div>
        </div>
      )}
      {blockers.length > 0 && (
        <div role="alert" className="rounded-md border border-destructive p-3 text-sm">
          <p className="font-medium">{t.missingTitle}</p>
          <ul className="list-disc pl-5">
            {blockers.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <p>{t.missingSuffix}</p>
        </div>
      )}
      {conflicts.length > 0 && (
        <div
          role="group"
          aria-labelledby="proposal-conflicts-title"
          className="rounded-md border border-destructive p-3 text-sm"
        >
          <h2 id="proposal-conflicts-title" className="font-medium">
            {r.conflictsTitle}
          </h2>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {conflicts.map((conflict, index) => (
              <li key={`${conflict.code}-${index}`}>
                {conflictText(conflict.code, conflict.fields.map(labelOf).join(" and "))}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-labelledby="source-title" className="space-y-3 rounded-lg border bg-card p-4">
          <h2 id="source-title" className="text-lg font-semibold">
            {t.sourceTitle}
          </h2>
          <SourcePanel documentId={documentId} />
          {documentId !== null && extractions.data && !newest && (
            <p className="text-sm">{t.sourceNoProposal}</p>
          )}
        </section>
        <form
          aria-labelledby="values-title"
          className="space-y-4 rounded-lg border bg-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void onSave();
          }}
        >
          <h2 id="values-title" className="text-lg font-semibold">
            {t.valuesTitle}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t.distributorLabel}: {latest.distributor ?? t.notFound}
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            {FIELD_NAMES.map((name) => {
              const id = `review-${name}`;
              return (
                <li key={name} className="space-y-2 rounded-md border p-3 text-sm">
                  <label htmlFor={id} className="block font-medium">
                    {labels[name]}
                  </label>
                  <Input
                    id={id}
                    name={id}
                    type={dateFields.has(name) ? "date" : "text"}
                    inputMode={dateFields.has(name) ? undefined : "decimal"}
                    autoComplete="off"
                    value={values[name]}
                    aria-describedby={`${id}-evidence`}
                    disabled={!active}
                    onChange={(event) => setValues({ ...values, [name]: event.target.value })}
                  />
                  <div id={`${id}-evidence`}>
                    <Evidence
                      name={name}
                      revision={base}
                      proposed={proposedByName.get(name)}
                      contradiction={contradictions.get(name)}
                      hasProposal={documentId !== null && newest !== undefined}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
          {active && (
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={busy || stale}>
                {save.isPending
                  ? t.saving
                  : latest.status === "confirmed"
                    ? t.saveCorrection
                    : t.saveChanges}
              </Button>
              <Button type="button" disabled={busy || !canConfirm} onClick={() => void onConfirm()}>
                {confirm.isPending ? t.confirming : t.confirmButton}
              </Button>
            </div>
          )}
          {latest.status === "confirmed" && <p className="text-sm">{t.alreadyConfirmed}</p>}
        </form>
      </div>
      {invoice.revisions.length > 1 && (
        <details className="text-sm">
          <summary className="cursor-pointer underline underline-offset-4">{t.history}</summary>
          <ol className="mt-2 space-y-2">
            {invoice.revisions.map((revision) => (
              <li key={revision.id}>
                {t.revisionLine(
                  revision.revision_number,
                  stateOf(invoice, revision),
                  revision.changed_fields.join(", ") || "none",
                  Object.entries(revision.old_values)
                    .map(([name, value]) => `${name} ${value ?? "empty"}`)
                    .join(", ") || "none",
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

export function InvoiceReview({ invoiceId, zone }: { invoiceId: string; zone: string }) {
  const query = useGetInvoice(invoiceId);
  if (query.isPending) return <p role="status">{t.loading}</p>;
  if (query.isError)
    return (
      <div role="alert" className="text-sm">
        {t.loadFailed}{" "}
        <Button type="button" variant="outline" onClick={() => void query.refetch()}>
          {t.retry}
        </Button>
      </div>
    );
  return <ReviewBody invoice={query.data} zone={zone} />;
}
