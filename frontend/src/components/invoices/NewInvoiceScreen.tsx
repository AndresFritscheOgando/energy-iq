"use client";

/** Manual invoice entry as its own page (spec 0012/0005 AC-1). Saves a draft, then opens review. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { createInvoice, getListInvoicesQueryKey } from "@/lib/api/generated/invoices/invoices";
import { useGetMeter } from "@/lib/api/generated/meters/meters";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { en } from "@/messages/en";

import { blank, body, Fields, message } from "./invoice-shared";

const t = en.invoiceScreens;

export function NewInvoiceScreen({ meterId }: { meterId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = useIdempotencyKey();
  const { data: meter } = useGetMeter(meterId);
  const [values, setValues] = useState(blank);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (data: ReturnType<typeof body>) =>
      createInvoice(meterId, data, {
        headers: { "Idempotency-Key": key.keyFor(JSON.stringify(data)) },
      }),
  });

  if (!meter) return <p role="status">{t.loading}</p>;
  if (!meter.active) {
    return <p className="rounded-md border bg-muted p-3 text-sm">{t.inactive}</p>;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    try {
      const created = await save.mutateAsync(body(values, meter!.distributor));
      key.reset();
      void queryClient.invalidateQueries({ queryKey: getListInvoicesQueryKey(meterId) });
      router.push(`/invoices/${created.id}`);
    } catch (error) {
      setProblem(message(error));
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="space-y-4 rounded-lg border bg-card p-5"
    >
      <p className="text-sm text-muted-foreground">
        {en.meterForm.distributorLabels[meter.distributor]}. {t.newIntro}
      </p>
      <Fields values={values} onChange={setValues} prefix="new-invoice" />
      {problem && (
        <p
          role="alert"
          className="rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {problem}
        </p>
      )}
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? t.saving : t.saveDraft}
      </Button>
    </form>
  );
}
