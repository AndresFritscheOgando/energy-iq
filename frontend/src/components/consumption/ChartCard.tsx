"use client";

/**
 * The chart's figure: legend, plot, readout, caption (spec 0011 child 0002
 * AC-5, AC-8). Recharts' tooltip and keyboard layer are off, because they follow
 * data points and can't be expected to reach bands. This app owned readout
 * covers steps and bands the same way and reads `model.segments`.
 */
import { Clock } from "lucide-react";
import dynamic from "next/dynamic";
import type { KeyboardEvent, PointerEvent } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { segmentIndexAtX, type ChartModel } from "@/lib/consumption/chart-model";
import { en } from "@/messages/en";

import { plotBounds } from "./chart-geometry";
import { SegmentGlyph } from "./SegmentGlyph";

export const CHART_HEIGHT_CLASS = "h-[280px]";

const UsageChart = dynamic(() => import("./UsageChart"), {
  ssr: false,
  loading: () => <Skeleton className="size-full rounded-md" />,
});

type Props = {
  model: ChartModel;
  selectedIndex: number;
  onSelect: (index: number) => void;
  stale: boolean;
  asOf: string | null;
  caption: string;
};

export function ChartCard({ model, selectedIndex, onSelect, stale, asOf, caption }: Props) {
  const segment = model.segments[selectedIndex] ?? null;
  const lastIndex = model.segments.length - 1;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = {
      ArrowLeft: Math.max(0, selectedIndex - 1),
      ArrowRight: Math.min(lastIndex, selectedIndex + 1),
      Home: 0,
      End: lastIndex,
    }[event.key];
    if (next !== undefined && lastIndex >= 0) {
      event.preventDefault();
      onSelect(next);
    }
  };

  const onPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const { left, width } = plotBounds(rect.width);
    const index = segmentIndexAtX(
      model.segments,
      event.clientX - rect.left - left,
      width,
      model.windowStartMs,
      model.windowEndMs,
    );
    if (index !== null && index !== selectedIndex) {
      onSelect(index);
    }
  };

  return (
    <figure className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs leading-4 text-muted-foreground">
          <li className="flex items-center gap-1.5">
            <SegmentGlyph kind="step" />
            {en.usage.legend.measured}
          </li>
          <li className="flex items-center gap-1.5">
            <SegmentGlyph kind="zero" />
            {en.usage.legend.zero}
          </li>
          <li className="flex items-center gap-1.5">
            <SegmentGlyph kind="gap" />
            {en.usage.legend.gap}
          </li>
          <li className="flex items-center gap-1.5">
            <SegmentGlyph kind="invalid" />
            {en.usage.legend.invalid}
          </li>
        </ul>
        {asOf && (
          <span className="flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs leading-4 text-muted-foreground">
            <Clock aria-hidden="true" className="size-3" />
            {en.usage.asOf(asOf)}
          </span>
        )}
      </div>

      <p className="text-[11px] leading-4 text-muted-foreground" aria-hidden="true">
        {en.usage.yAxis}
      </p>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        role="group"
        // One tab stop that owns its arrow keys; the readout below announces them.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        aria-label={en.usage.chartLabel}
        data-testid="usage-chart"
        onKeyDown={onKeyDown}
        onPointerMove={onPointer}
        onPointerDown={onPointer}
        className={`-mt-2 w-full rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring ${CHART_HEIGHT_CLASS}`}
      >
        <UsageChart model={model} selectedKey={segment?.key ?? null} stale={stale} />
      </div>

      <div className="flex min-h-[72px] flex-col gap-0.5 border-t pt-3 sm:min-h-[52px]">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 text-xs leading-4 text-muted-foreground">
          <span className="font-semibold">{segment?.kindLabel}</span>
          <span>{en.usage.hint}</span>
        </div>
        <p aria-live="polite" data-testid="chart-readout" className="text-sm leading-5">
          {segment?.readout}
        </p>
      </div>

      <figcaption className="text-[13px] leading-5 text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}
