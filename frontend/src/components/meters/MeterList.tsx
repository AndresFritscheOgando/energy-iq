"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { ListSkeleton, LoadMore, SectionError } from "@/components/app/ListParts";
import { metersListOptions } from "@/lib/api/list-queries";
import { en } from "@/messages/en";

export function MeterList({ propertyId }: { propertyId: string }) {
  const query = useInfiniteQuery(metersListOptions(propertyId));

  if (query.isPending) {
    return <ListSkeleton />;
  }
  if (!query.data) {
    return (
      <SectionError
        name={en.property.metersTitle}
        error={query.error}
        retrying={query.isFetching}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const rows = query.data.pages.flatMap((page) => page.items);
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-5">
        <h3 className="text-sm leading-5 font-semibold">{en.property.emptyTitle}</h3>
        <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{en.property.emptyBody}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ul aria-labelledby="meters-title" className="divide-y rounded-lg border bg-card">
        {rows.map((meter) => (
          <li key={meter.id}>
            <Link
              href={`/meters/${meter.id}`}
              className="flex min-h-11 items-center justify-between gap-3 px-4 py-3 hover:bg-muted/60"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-sm leading-5 break-words">{meter.label}</span>
                <span className="text-[13px] leading-5 text-muted-foreground">
                  {en.meterForm.distributorLabels[meter.distributor]}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                {!meter.active && (
                  <span className="rounded-full border bg-muted px-2 py-0.5 text-xs leading-4 text-muted-foreground">
                    {en.property.inactive}
                  </span>
                )}
                <ChevronRight aria-hidden="true" className="size-4 text-muted-foreground" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <LoadMore
        hasNextPage={query.hasNextPage}
        fetching={query.isFetchingNextPage}
        failed={query.isFetchNextPageError}
        error={query.error}
        onLoadMore={() => void query.fetchNextPage()}
      />
    </div>
  );
}
