"use client";

/**
 * Upload a bill PDF to a meter and watch its extraction run (spec 0012/0005 AC-1).
 *
 * There is no list route for documents yet, so this shows only the uploads made
 * on this page visit. A document ready for review opens the proposal review.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ProposalReview } from "@/components/documents/ProposalReview";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import {
  getDocument,
  getGetDocumentQueryKey,
  getDownloadSourceUrl,
  retryDocument,
  uploadDocument,
} from "@/lib/api/generated/documents/documents";
import type { Distributor, DocumentOut } from "@/lib/api/generated/model";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { en } from "@/messages/en";

const t = en.documents;
const POLL_MS = 2000;

function uploadMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "upload_too_large") return t.tooLarge;
    if (error.code === "upload_not_pdf") return t.notPdf;
    if (error.code === "upload_invalid" || error.code === "pdf_invalid") return t.invalid;
    if (error.code === "too_many_active") return t.tooMany;
    if (error.code === "meter_inactive") return t.inactive;
  }
  return t.failed;
}

function retryMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "retries_exhausted") return t.retryExhausted;
    if (error.code === "run_active") return t.retryBusy;
    if (error.code === "too_many_active") return t.tooMany;
    if (error.code === "meter_inactive") return t.inactive;
  }
  return t.retryFailed;
}

function isSettled(doc: DocumentOut): boolean {
  return doc.run === null || (doc.run.state !== "queued" && doc.run.state !== "running");
}

function DocumentRow({
  initial,
  meterId,
  distributor,
  active,
}: {
  initial: DocumentOut;
  meterId: string;
  distributor: Distributor;
  active: boolean;
}) {
  const [reviewing, setReviewing] = useState(false);
  const queryClient = useQueryClient();
  const key = useIdempotencyKey();
  const { data } = useQuery({
    queryKey: getGetDocumentQueryKey(initial.id),
    queryFn: () => getDocument(initial.id),
    initialData: initial,
    refetchInterval: (query) => (query.state.data && isSettled(query.state.data) ? false : POLL_MS),
  });
  const doc = data ?? initial;
  const retry = useMutation({
    mutationFn: () =>
      retryDocument(doc.id, { headers: { "Idempotency-Key": key.keyFor(doc.run?.id ?? doc.id) } }),
    onSuccess: (next) => {
      key.reset();
      queryClient.setQueryData(getGetDocumentQueryKey(doc.id), next);
    },
  });

  return (
    <li className="space-y-3 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-medium">{t.state[doc.state]}</span>
          <span className="ml-2 text-xs text-muted-foreground">
            {(doc.size_bytes / 1024).toFixed(0)} KB
          </span>
          {doc.state === "failed" && <p className="text-muted-foreground">{t.failedReason}</p>}
          {retry.isError && (
            <p role="alert" className="text-destructive">
              {retryMessage(retry.error)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {doc.state === "needs_review" && active && (
            <Button
              type="button"
              variant="outline"
              aria-expanded={reviewing}
              onClick={() => setReviewing((open) => !open)}
            >
              {reviewing ? t.closeReview : t.review}
            </Button>
          )}
          {doc.state === "failed" && (
            <Button
              type="button"
              variant="outline"
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            >
              {t.retry}
            </Button>
          )}
          <a className="underline underline-offset-4" href={getDownloadSourceUrl(doc.id)} download>
            {t.download}
          </a>
        </div>
      </div>
      {reviewing && doc.state === "needs_review" && (
        <ProposalReview documentId={doc.id} meterId={meterId} distributor={distributor} />
      )}
    </li>
  );
}

export function DocumentUpload({
  meterId,
  active,
  distributor,
}: {
  meterId: string;
  active: boolean;
  distributor: Distributor;
}) {
  const key = useIdempotencyKey();
  const inputRef = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<DocumentOut[]>([]);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      // Some browsers label a real PDF with another type (or none). The server
      // checks the bytes, so send the type it expects and let it decide.
      form.append("file", new Blob([file], { type: "application/pdf" }), file.name);
      const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;
      return uploadDocument(meterId, {
        body: form,
        headers: { "Idempotency-Key": key.keyFor(fingerprint) },
      });
    },
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    const file = inputRef.current?.files?.[0];
    if (!file) return setProblem(t.noFile);
    if (!file.name.toLowerCase().endsWith(".pdf")) return setProblem(t.notPdfName);
    try {
      const doc = await upload.mutateAsync(file);
      key.reset();
      setUploaded((rows) => [doc, ...rows.filter((row) => row.id !== doc.id)]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (error) {
      setProblem(uploadMessage(error));
    }
  }

  return (
    <section aria-labelledby="documents-title" className="space-y-3 border-b pb-5">
      <div>
        <h3 id="documents-title" className="font-medium">
          {t.title}
        </h3>
        <p className="text-sm text-muted-foreground">{t.hint}</p>
      </div>
      {problem && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {problem}
        </p>
      )}
      {active ? (
        <form onSubmit={(event) => void submit(event)} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm font-medium">
            <span>{t.fileLabel}</span>
            <Input ref={inputRef} type="file" name="file" accept="application/pdf,.pdf" />
          </label>
          <Button type="submit" disabled={upload.isPending}>
            {upload.isPending ? t.pending : t.submit}
          </Button>
        </form>
      ) : (
        <p className="text-sm text-muted-foreground">{t.inactive}</p>
      )}
      {uploaded.length > 0 && (
        <div aria-live="polite" className="space-y-2">
          <h4 className="text-sm font-medium">{t.listTitle}</h4>
          <ul className="space-y-2">
            {uploaded.map((doc) => (
              <DocumentRow
                key={doc.id}
                initial={doc}
                meterId={meterId}
                distributor={distributor}
                active={active}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
