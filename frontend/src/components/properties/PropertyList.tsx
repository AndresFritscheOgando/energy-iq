"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { ListSkeleton, LoadMore, SectionError } from "@/components/app/ListParts";
import { propertiesListOptions } from "@/lib/api/list-queries";
import { en } from "@/messages/en";

export function PropertyList() {
  const query = useInfiniteQuery(propertiesListOptions());

  if (query.isPending) {
    return <ListSkeleton />;
  }
  if (!query.data) {
    return (
      <SectionError
        name={en.home.breadcrumb}
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
        <h2 className="text-sm leading-5 font-semibold">{en.home.emptyTitle}</h2>
        <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{en.home.emptyBody}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ul aria-label={en.home.listLabel} className="divide-y rounded-lg border bg-card">
        {rows.map((property) => (
          <li key={property.id}>
            <Link
              href={`/properties/${property.id}`}
              className="flex min-h-11 items-center justify-between gap-3 px-4 py-3 hover:bg-muted/60"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-sm leading-5 break-words">{property.nickname}</span>
                {property.region && (
                  <span className="text-[13px] leading-5 break-words text-muted-foreground">
                    {property.region}
                  </span>
                )}
              </span>
              <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
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
