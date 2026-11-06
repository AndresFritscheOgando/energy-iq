"use client";

/**
 * The invoice list for one meter (spec 0012/0005 AC-1): paged, with manual
 * entry and upload actions, and loading, empty, error, and retry states.
 * Each row opens the review screen; nothing is confirmed from the list.
 */
import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";

import { DocumentUpload } from "@/components/documents/DocumentUpload";
import { Button } from "@/components/ui/button";
import { getListInvoicesQueryKey, listInvoices } from "@/lib/api/generated/invoices/invoices";
import { useGetMeter } from "@/lib/api/generated/meters/meters";
import { formatDateTime } from "@/lib/format";
import { en } from "@/messages/en";

const t = en.invoiceScreens;
const PAGE_SIZE = 20;

export function InvoiceListScreen({ meterId, zone }: { meterId: string; zone: string }) {
  const { data: meter } = useGetMeter(meterId);
  const active = meter?.active !== false;
  const list = useInfiniteQuery({
    queryKey: [...getListInvoicesQueryKey(meterId), "screen"],
    queryFn: ({ pageParam }) =>
      listInvoices(meterId, { limit: PAGE_SIZE, cursor: pageParam ?? undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const invoices = list.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section aria-labelledby="invoice-list-title" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="invoice-list-title" className="text-lg font-semibold">
            {t.listTitle}
          </h2>
          <p className="text-sm text-muted-foreground">{t.listIntro}</p>
        </div>
        {active && (
          <Link
            href={`/meters/${meterId}/invoices/new`}
            className="inline-flex h-8 items-center rounded-lg border px-3 text-sm font-medium"
          >
            {t.enterManually}
          </Link>
        )}
      </div>
      {!active && <p className="rounded-md border bg-muted p-3 text-sm">{t.inactive}</p>}
      {meter && (
        <DocumentUpload meterId={meterId} active={active} distributor={meter.distributor} />
      )}
      {list.isPending && <p role="status">{t.loading}</p>}
      {list.isError && (
        <div role="alert" className="text-sm">
          {t.loadFailed}{" "}
          <Button type="button" variant="outline" onClick={() => void list.refetch()}>
            {t.retry}
          </Button>
        </div>
      )}
      {list.data && invoices.length === 0 && (
        <p className="text-sm text-muted-foreground">{t.empty}</p>
      )}
      {invoices.length > 0 && (
        <ul className="grid gap-4 lg:grid-cols-2">
          {invoices.map((invoice) => {
            const latest = invoice.revisions.at(-1)!;
            const when = formatDateTime(latest.created_at, "dateTime", zone) ?? latest.created_at;
            return (
              <li key={invoice.id} className="space-y-2 rounded-lg border bg-card p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold">
                      {latest.period_start ?? t.periodNeeded} to{" "}
                      {latest.period_end ?? t.periodNeeded}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      {latest.billed_kwh ?? t.useNeeded} kWh · DOP{" "}
                      {latest.total_dop ?? t.totalNeeded}
                    </p>
                  </div>
                  <span className="rounded-full bg-muted px-2 py-1 text-xs">
                    {latest.status === "draft" ? t.draft : t.confirmed}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {latest.source_document_id ? t.sourceDocument : t.sourceManual}.{" "}
                  {t.recorded(when)} Revision {latest.revision_number}.
                </p>
                <Link
                  href={`/invoices/${invoice.id}`}
                  className="inline-block text-sm underline underline-offset-4"
                >
                  {t.review}
                  <span className="sr-only">
                    {" "}
                    {latest.period_start ?? t.periodNeeded} to {latest.period_end ?? t.periodNeeded}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {list.hasNextPage && (
        <Button
          type="button"
          variant="outline"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          {list.isFetchingNextPage ? t.loadingMore : t.loadMore}
        </Button>
      )}
    </section>
  );
}
