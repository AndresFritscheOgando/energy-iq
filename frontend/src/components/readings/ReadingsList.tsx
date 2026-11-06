"use client";

/**
 * The meter's readings, newest first, and voiding (spec 0011 child 0001 AC-9,
 * AC-10). Reading values can't be edited, so a confirmed void is the only fix
 * for a typo. Voiding an already voided reading answers 200, so a stale tab is
 * a normal success.
 */
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ListSkeleton, LoadMore, SectionError } from "@/components/app/ListParts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { genericErrorMessage } from "@/lib/api/form-errors";
import { changeReadingStatus } from "@/lib/api/generated/default/default";
import type { ReadingOut } from "@/lib/api/generated/model";
import { invalidateMeterData, readingsListOptions } from "@/lib/api/list-queries";
import { formatExact, parseDecimal } from "@/lib/decimal";
import { en } from "@/messages/en";

import { readingDate } from "./ReadingForm";

function displayValue(reading: ReadingOut): string {
  const parsed = parseDecimal(reading.cumulative_kwh);
  return parsed === null ? en.readings.notAvailable : formatExact(parsed);
}

const VOID_ATTRIBUTE = "data-void-reading";

export function ReadingsList({ meterId, zone }: { meterId: string; zone: string }) {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery(readingsListOptions(meterId));
  const mutation = useMutation({
    mutationFn: (readingId: string) =>
      changeReadingStatus(meterId, readingId, { status: "voided" }),
  });

  const [target, setTarget] = useState<ReadingOut | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const openerRef = useRef<string | null>(null);

  const rows = query.data?.pages.flatMap((page) => page.items) ?? [];

  const focusAfterClose = (readingId: string | null) => {
    // After the dialog releases focus, and after a refetch may have moved rows.
    requestAnimationFrame(() => {
      const button =
        readingId === null
          ? null
          : document.querySelector<HTMLElement>(`[${VOID_ATTRIBUTE}="${readingId}"]`);
      (button ?? headingRef.current)?.focus();
    });
  };

  const close = () => {
    setTarget(null);
    setFailure(null);
    focusAfterClose(openerRef.current);
  };

  const confirm = async () => {
    if (target === null || mutation.isPending) {
      return;
    }
    setFailure(null);
    try {
      await mutation.mutateAsync(target.id);
    } catch (error) {
      setFailure(genericErrorMessage(error));
      return;
    }
    const index = rows.findIndex((row) => row.id === target.id);
    const next = rows.slice(index + 1).find((row) => row.status !== "voided");
    setAnnouncement(
      en.readings.voided_announcement(displayValue(target), readingDate(target, zone, "long")),
    );
    setTarget(null);
    focusAfterClose(next?.id ?? null);
    void invalidateMeterData(queryClient, meterId);
  };

  return (
    <section
      aria-labelledby="readings-title"
      className="flex flex-col gap-3 min-[900px]:col-span-2"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2
          id="readings-title"
          ref={headingRef}
          tabIndex={-1}
          className="text-base leading-6 font-semibold outline-none"
        >
          {en.readings.title}
        </h2>
        <span className="text-[13px] leading-5 text-muted-foreground">
          {en.readings.newestFirst}
        </span>
      </div>

      <p role="status" className="sr-only">
        {announcement}
      </p>

      {query.isPending ? (
        <ListSkeleton rows={4} />
      ) : !query.data ? (
        <SectionError
          name={en.readings.sectionName}
          error={query.error}
          retrying={query.isFetching}
          onRetry={() => void query.refetch()}
        />
      ) : rows.length === 0 ? (
        <div className="rounded-lg border bg-card p-5">
          <h3 className="text-sm leading-5 font-semibold">{en.readings.emptyTitle}</h3>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
            {en.readings.emptyBody}
          </p>
        </div>
      ) : (
        <>
          <ul aria-labelledby="readings-title" className="divide-y rounded-lg border bg-card">
            {rows.map((reading) => {
              const value = displayValue(reading);
              const date = readingDate(reading, zone, "medium");
              const voided = reading.status === "voided";
              const struck = voided ? "line-through text-muted-foreground" : "";
              return (
                <li
                  key={reading.id}
                  id={`reading-${reading.id}`}
                  tabIndex={-1}
                  className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 px-4 py-3 text-sm leading-5 outline-none focus-visible:bg-accent sm:grid-cols-[1fr_11rem_8rem_auto]"
                >
                  <span className={struck}>{date}</span>
                  <span
                    className={`col-start-1 font-medium sm:col-start-auto sm:text-right ${struck}`}
                  >
                    {en.readings.value(value)}
                  </span>
                  <span className="col-start-1 text-[13px] text-muted-foreground sm:col-start-auto">
                    {voided && en.readings.voided}
                    {reading.status === "flagged" && en.readings.flagged}
                  </span>
                  <span className="col-start-2 row-span-3 row-start-1 justify-self-end sm:col-start-auto sm:row-span-1 sm:row-start-auto">
                    {!voided && (
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={en.readings.voidLabel(value, date)}
                        {...{ [VOID_ATTRIBUTE]: reading.id }}
                        onClick={() => {
                          openerRef.current = reading.id;
                          setFailure(null);
                          setTarget(reading);
                        }}
                      >
                        {en.readings.void}
                      </Button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
          <LoadMore
            hasNextPage={query.hasNextPage}
            fetching={query.isFetchingNextPage}
            failed={query.isFetchNextPageError}
            error={query.error}
            summary={en.lists.showing(rows.length, en.readings.noun)}
            onLoadMore={() => void query.fetchNextPage()}
          />
        </>
      )}

      <AlertDialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open && !mutation.isPending) {
            close();
          }
        }}
      >
        {target && (
          <AlertDialogContent finalFocus={false} className="data-[size=default]:sm:max-w-md">
            <AlertDialogHeader>
              <AlertDialogTitle>{en.readings.voidTitle}</AlertDialogTitle>
              <AlertDialogDescription className="text-foreground">
                <strong className="font-semibold">
                  {en.readings.voidBodyLead(
                    displayValue(target),
                    readingDate(target, zone, "long"),
                  )}
                </strong>
                {en.readings.voidBodyRest}
              </AlertDialogDescription>
            </AlertDialogHeader>
            {failure && (
              <Alert variant="destructive">
                <AlertDescription>{failure}</AlertDescription>
              </Alert>
            )}
            <AlertDialogFooter>
              <Button type="button" variant="outline" disabled={mutation.isPending} onClick={close}>
                {en.readings.voidCancel}
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={mutation.isPending}
                onClick={() => void confirm()}
              >
                {mutation.isPending ? en.readings.voidPending : en.readings.voidConfirm}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        )}
      </AlertDialog>
    </section>
  );
}
