"use client";

/**
 * The usage view (spec 0011 child 0002 AC-9). It fails by itself, so the
 * reading form and list keep working. Renders two grid items: the main column
 * and the full width table. The browser does the fetching when the server
 * prefetch failed; during server rendering `useQuery` sends nothing.
 */
import { Clock, CircleAlert, Info, RotateCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiUnavailableError } from "@/lib/api/errors";
import { genericErrorMessage } from "@/lib/api/form-errors";
import { useStoredConsumption } from "@/lib/api/generated/default/default";
import { toChartModel } from "@/lib/consumption/chart-model";
import { formatLength } from "@/lib/consumption/duration";
import { formatDecimal, formatPercent, parseDecimal } from "@/lib/decimal";
import { formatDateTime } from "@/lib/format";
import { RANGES, nextLongerRange, type ConsumptionWindow, type Range } from "@/lib/zoned-time";
import { en } from "@/messages/en";

import { ChartCard, CHART_HEIGHT_CLASS } from "./ChartCard";
import { IntervalsTable } from "./IntervalsTable";

type Props = {
  meterId: string;
  zone: string;
  range: Range;
  window: ConsumptionWindow;
  canAddReadings: boolean;
};

function requestIdOf(error: unknown): string | null {
  return error !== null && typeof error === "object" && "requestId" in error
    ? (error.requestId as string | null)
    : null;
}

function RangeControl({ meterId, range }: { meterId: string; range: Range }) {
  return (
    <nav aria-label={en.usage.rangeLabel}>
      <ul className="flex gap-0.5 rounded-lg border bg-muted p-0.5">
        {RANGES.map((option) => (
          <li key={option}>
            <Link
              href={`/meters/${meterId}?range=${option}`}
              scroll={false}
              prefetch={false}
              aria-current={option === range ? "page" : undefined}
              className={
                "flex h-11 items-center rounded-md px-3 text-[13px] whitespace-nowrap sm:h-8 " +
                (option === range
                  ? "border border-input bg-card font-medium"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              {en.usage.ranges[option]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Tile({
  label,
  value,
  unit,
  note,
  muted,
}: {
  label: string;
  value: string;
  unit?: string;
  note: string;
  muted: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 p-4">
      <dt className="text-[13px] leading-5 text-muted-foreground">{label}</dt>
      <dd
        className={`flex flex-wrap items-baseline gap-x-1 text-[22px] leading-7 font-medium sm:text-3xl sm:leading-9 ${muted ? "text-muted-foreground" : ""}`}
      >
        {value}
        {unit && <span className="text-[13px] font-normal text-muted-foreground">{unit}</span>}
      </dd>
      <dd className="text-xs leading-4 text-muted-foreground">{note}</dd>
    </div>
  );
}

function TileRow({ children }: { children: React.ReactNode }) {
  return (
    <dl className="grid grid-cols-3 divide-x rounded-lg border bg-card max-[420px]:grid-cols-1 max-[420px]:divide-x-0 max-[420px]:divide-y">
      {children}
    </dl>
  );
}

function LoadingState() {
  return (
    <>
      <p role="status" className="text-[13px] leading-5 text-muted-foreground">
        {en.usage.loading}
      </p>
      <Skeleton className="h-28 w-full rounded-lg" />
      <Skeleton className={`w-full rounded-lg ${CHART_HEIGHT_CLASS}`} />
    </>
  );
}

function ErrorState({
  error,
  retrying,
  onRetry,
}: {
  error: unknown;
  retrying: boolean;
  onRetry: () => void;
}) {
  const requestId = requestIdOf(error);
  const unavailable = error instanceof ApiUnavailableError;
  return (
    <Alert variant="destructive" className="gap-y-2 p-4">
      <CircleAlert />
      <AlertTitle className="text-foreground">{en.usage.errorTitle}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        <span className="text-muted-foreground">
          {unavailable ? en.unavailable.message : en.usage.errorBody}
        </span>
        {requestId && (
          <span className="text-muted-foreground">{en.usage.reference(requestId)}</span>
        )}
        <Button type="button" variant="outline" disabled={retrying} onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {retrying ? en.usage.retrying : en.usage.retry}
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function StaleNotice({
  error,
  asOf,
  retrying,
  onRetry,
}: {
  error: unknown;
  asOf: string;
  retrying: boolean;
  onRetry: () => void;
}) {
  const requestId = requestIdOf(error);
  return (
    <div role="alert" className="flex gap-2.5 rounded-lg border border-warning bg-warning/10 p-4">
      <Clock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
      <div className="flex flex-col items-start gap-1.5 text-sm leading-5">
        <p className="font-semibold text-warning-foreground">{en.usage.staleTitle}</p>
        <p>{en.usage.staleBody(asOf)}</p>
        {requestId ? (
          <p className="text-[13px] text-muted-foreground">{en.usage.reference(requestId)}</p>
        ) : (
          error instanceof ApiUnavailableError && (
            <p className="text-[13px] text-muted-foreground">{genericErrorMessage(error)}</p>
          )
        )}
        <Button type="button" variant="outline" disabled={retrying} onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {retrying ? en.usage.retrying : en.usage.retry}
        </Button>
      </div>
    </div>
  );
}

export function UsageSection({ meterId, zone, range, window, canAddReadings }: Props) {
  // The window is the server's prop, never recomputed here: one query key.
  const query = useStoredConsumption(meterId, window);
  const [selected, setSelected] = useState<{ modelKey: number; index: number } | null>(null);

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base leading-6 font-semibold">{en.usage.title}</h2>
      <RangeControl meterId={meterId} range={range} />
    </div>
  );
  const sectionClass =
    "flex min-w-0 flex-col gap-4 min-[900px]:col-start-1 min-[900px]:row-start-1";

  if (query.isPending) {
    return (
      <section aria-label={en.usage.title} className={sectionClass}>
        {header}
        <LoadingState />
      </section>
    );
  }

  const data = query.data;
  if (!data) {
    return (
      <section aria-label={en.usage.title} className={sectionClass}>
        {header}
        <ErrorState
          error={query.error}
          retrying={query.isFetching}
          onRetry={() => void query.refetch()}
        />
      </section>
    );
  }

  const measured = data.intervals.filter((interval) => interval.measured_in_window);
  const hasMeasured = measured.length > 0;
  const hasGaps = data.gaps.length > 0;
  const stale = query.isError;
  const staleNotice = stale ? (
    <StaleNotice
      error={query.error}
      asOf={formatDateTime(new Date(query.dataUpdatedAt).toISOString(), "time", zone) ?? ""}
      retrying={query.isFetching}
      onRetry={() => void query.refetch()}
    />
  ) : null;

  const needsReadings = hasGaps && data.gaps.every((gap) => gap.reason === "no_intervals");
  if (needsReadings && !hasMeasured) {
    return (
      <section aria-label={en.usage.title} className={sectionClass}>
        {header}
        {staleNotice}
        <div className="flex min-h-48 flex-col items-start justify-center gap-2 rounded-lg border bg-card p-6">
          <h3 className="text-base leading-6 font-semibold">{en.usage.needsTitle}</h3>
          <p className="text-[13px] leading-5 text-muted-foreground">{en.usage.needsBody}</p>
          {canAddReadings && (
            <a
              href="#reading-value"
              className={buttonVariants({ variant: "outline", className: "mt-1" })}
            >
              {en.usage.needsLink}
            </a>
          )}
        </div>
      </section>
    );
  }

  const model = toChartModel(data, zone);
  const modelKey = query.dataUpdatedAt;
  const selectedIndex =
    selected !== null && selected.modelKey === modelKey && selected.index < model.segments.length
      ? selected.index
      : model.defaultSegmentIndex;
  const select = (index: number) => setSelected({ modelKey, index });

  const ratio = parseDecimal(data.coverage_ratio);
  const coverage = ratio ? formatPercent(ratio, { hasGaps, hasMeasured }) : en.usage.notAvailable;
  const measuredKwh = parseDecimal(data.measured_kwh);
  const measuredText = measuredKwh ? formatDecimal(measuredKwh, 2) : en.usage.notAvailable;
  const average = data.average_kwh_per_day === null ? null : parseDecimal(data.average_kwh_per_day);
  const averageText = average ? formatDecimal(average, 2) : en.usage.notAvailable;
  const coveredLength = formatLength(data.covered);
  const longer = nextLongerRange(range);

  return (
    <>
      <section aria-label={en.usage.title} className={sectionClass}>
        {header}
        {staleNotice}
        {!hasMeasured && (
          <div className="flex gap-2.5 rounded-lg border bg-card p-4">
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div className="flex flex-col gap-1 text-sm leading-5">
              <p className="font-semibold">
                {en.usage.nothingTitle(en.usage.rangeSentence[range])}
              </p>
              {longer && (
                <Link
                  href={`/meters/${meterId}?range=${longer}`}
                  scroll={false}
                  prefetch={false}
                  className="text-primary underline underline-offset-4"
                >
                  {en.usage.nothingLink(en.usage.rangeSentence[longer])}
                </Link>
              )}
            </div>
          </div>
        )}
        <TileRow>
          <Tile
            label={en.usage.tiles.measured}
            value={measuredText}
            unit={measuredKwh ? en.usage.tiles.unit : undefined}
            note={hasMeasured && coveredLength ? en.usage.tiles.over(coveredLength) : " "}
            muted={stale}
          />
          <Tile
            label={en.usage.tiles.average}
            value={averageText}
            unit={average ? en.usage.tiles.unit : undefined}
            note={hasMeasured ? en.usage.tiles.measuredOnly : " "}
            muted={stale}
          />
          <Tile
            label={en.usage.tiles.coverage}
            value={coverage}
            note={en.usage.tiles.ofRange(en.usage.rangeSentence[range])}
            muted={stale}
          />
        </TileRow>
        {hasMeasured && hasGaps && (
          <p className="flex items-start gap-2 text-[13px] leading-5 text-muted-foreground">
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {en.usage.partial(coverage)}
          </p>
        )}
        <ChartCard
          model={model}
          selectedIndex={selectedIndex}
          onSelect={select}
          stale={stale}
          asOf={
            stale
              ? (formatDateTime(new Date(query.dataUpdatedAt).toISOString(), "time", zone) ?? "")
              : null
          }
          caption={en.usage.caption(
            en.usage.rangeSentence[range],
            measuredText,
            averageText,
            coverage,
            data.gaps.length,
          )}
        />
      </section>
      <IntervalsTable rows={model.rows} selectedKey={model.segments[selectedIndex]?.key ?? null} />
    </>
  );
}
