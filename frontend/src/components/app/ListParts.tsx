"use client";

/**
 * The list section states every list shares (spec 0011): loading is a skeleton
 * with reserved height, a failed first page has its own message with Retry, and
 * a failed "Load more" keeps the rows with an inline message.
 */
import { CircleAlert, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { genericErrorMessage } from "@/lib/api/form-errors";
import { en } from "@/messages/en";

export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label={en.lists.loading} className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-16 w-full rounded-lg" />
      ))}
    </div>
  );
}

export function SectionError({
  name,
  error,
  retrying,
  onRetry,
}: {
  name: string;
  error: unknown;
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive" className="gap-y-2 p-4">
      <CircleAlert />
      <AlertTitle className="text-foreground">{en.lists.sectionFailed(name)}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        <span>{genericErrorMessage(error)}</span>
        <Button type="button" variant="outline" disabled={retrying} onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {retrying ? en.lists.retrying : en.lists.retry}
        </Button>
      </AlertDescription>
    </Alert>
  );
}

export function LoadMore({
  hasNextPage,
  fetching,
  failed,
  error,
  summary,
  onLoadMore,
}: {
  hasNextPage: boolean;
  fetching: boolean;
  failed: boolean;
  error: unknown;
  summary?: ReactNode;
  onLoadMore: () => void;
}) {
  if (!hasNextPage) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button type="button" variant="outline" disabled={fetching} onClick={onLoadMore}>
        {fetching ? en.lists.loadingMore : failed ? en.lists.retry : en.lists.loadMore}
      </Button>
      {summary && !failed && (
        <span className="text-[13px] leading-5 text-muted-foreground">{summary}</span>
      )}
      {failed && (
        <span role="alert" className="text-[13px] leading-5 text-destructive">
          {en.lists.loadFailed} {genericErrorMessage(error)}
        </span>
      )}
    </div>
  );
}
