"use client";

/**
 * The drawing (spec 0011 child 0002 AC-3, AC-4). Steps and bands come from the
 * model and nothing else is drawn. Loaded with `ssr: false`, because Recharts
 * needs a browser to measure, and only the meter page pays for its bundle.
 */
import { useId } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  XAxis,
  YAxis,
  usePlotArea,
  useXAxisScale,
  useYAxisScale,
} from "recharts";

import { ChartContainer } from "@/components/ui/chart";
import type { ChartModel, Segment } from "@/lib/consumption/chart-model";

import { CHART_MARGIN, Y_AXIS_WIDTH } from "./chart-geometry";

const MIN_BAND_PX = 2;
const CONFIG = {};

type BandShapeProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
};

function bandShape(invalid: boolean, gapId: string, invalidId: string) {
  function BandShape({ x = 0, y = 0, width = 0, height = 0 }: BandShapeProps) {
    // A render step only: the model's spans stay exact.
    const drawn = Math.max(MIN_BAND_PX, width);
    const left = x - (drawn - width) / 2;
    return (
      <g>
        <rect
          x={left}
          y={y}
          width={drawn}
          height={height}
          fill={`url(#${invalid ? invalidId : gapId})`}
        />
        {invalid && (
          <path d={`M${x + width / 2 - 5} ${y - 9}h10l-5 7z`} fill="var(--chart-invalid)" />
        )}
      </g>
    );
  }
  return BandShape;
}

/** A measured zero: a 3 px bar on the baseline with end ticks, no hatching. */
function ZeroMarks({ segments, color }: { segments: readonly Segment[]; color: string }) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  if (!xScale || !yScale) {
    return null;
  }
  const baseline = yScale(0) ?? 0;
  return (
    <g className="chart-zero">
      {segments
        .filter((segment) => segment.kind === "zero")
        .map((segment) => {
          const left = xScale(segment.startMs) ?? 0;
          const right = xScale(segment.endMs) ?? 0;
          const width = Math.max(3, right - left);
          return (
            <g key={segment.key} fill={color}>
              <rect x={left} y={baseline - 3} width={width} height={3} />
              <rect x={left} y={baseline - 8} width={2} height={8} />
              <rect x={left + width - 2} y={baseline - 8} width={2} height={8} />
            </g>
          );
        })}
    </g>
  );
}

/** A 2 px outline on the selected step or band. */
function SelectionOutline({ segment }: { segment: Segment | null }) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  const plot = usePlotArea();
  if (!segment || !xScale || !yScale || !plot) {
    return null;
  }
  const left = xScale(segment.startMs) ?? plot.x;
  const right = xScale(segment.endMs) ?? plot.x;
  const top = segment.y === null ? plot.y : Math.max(plot.y, (yScale(segment.y) ?? plot.y) - 3);
  const bottom = plot.y + plot.height;
  return (
    <rect
      data-testid="chart-selection"
      x={left - 1}
      y={top}
      width={Math.max(3, right - left) + 2}
      height={Math.max(8, bottom - top)}
      rx={2}
      fill="none"
      stroke="var(--foreground)"
      strokeWidth={2}
      pointerEvents="none"
    />
  );
}

type Props = {
  model: ChartModel;
  selectedKey: string | null;
  stale: boolean;
};

export default function UsageChart({ model, selectedKey, stale }: Props) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const gapId = `hatch-gap-${id}`;
  const invalidId = `hatch-invalid-${id}`;
  const measuredColor = stale ? "var(--muted-foreground)" : "var(--chart-measured)";
  const domain: [number, number] = [model.windowStartMs, model.windowEndMs];
  // With nothing measured the axes still need data to lay out against.
  const data = model.points.length
    ? model.points
    : [
        { x: model.windowStartMs, y: null },
        { x: model.windowEndMs, y: null },
      ];
  const labels = new Map(model.xTicks.map((tick) => [tick.value, tick.label]));
  const selected = model.segments.find((segment) => segment.key === selectedKey) ?? null;

  return (
    <ChartContainer config={CONFIG} className="aspect-auto size-full">
      <ComposedChart data={data} margin={CHART_MARGIN} accessibilityLayer={false}>
        <defs>
          <pattern
            id={gapId}
            patternUnits="userSpaceOnUse"
            width="6"
            height="6"
            patternTransform="rotate(45)"
          >
            <rect
              width="6"
              height="6"
              style={{ fill: "color-mix(in oklch, var(--chart-gap) 7%, transparent)" }}
            />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="6"
              style={{ stroke: "var(--chart-gap)", strokeWidth: 1.25 }}
            />
          </pattern>
          <pattern
            id={invalidId}
            patternUnits="userSpaceOnUse"
            width="8"
            height="8"
            patternTransform="rotate(45)"
          >
            <rect
              width="8"
              height="8"
              style={{ fill: "color-mix(in oklch, var(--chart-invalid) 8%, transparent)" }}
            />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              style={{ stroke: "var(--chart-invalid)", strokeWidth: 1.25 }}
            />
            <line
              x1="0"
              y1="0"
              x2="8"
              y2="0"
              style={{ stroke: "var(--chart-invalid)", strokeWidth: 1.25 }}
            />
          </pattern>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis
          dataKey="x"
          type="number"
          domain={domain}
          ticks={model.xTicks.map((tick) => tick.value)}
          tickFormatter={(value: number) => labels.get(value) ?? ""}
          allowDataOverflow
          interval="preserveStartEnd"
          minTickGap={12}
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
        />
        <YAxis
          type="number"
          domain={[0, model.yTop]}
          ticks={model.yTicks}
          width={Y_AXIS_WIDTH}
          allowDataOverflow
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
        />
        {model.bands.map((band) => (
          <ReferenceArea
            key={band.key}
            x1={band.startMs}
            x2={band.endMs}
            y1={0}
            y2={model.yTop}
            ifOverflow="visible"
            className={band.invalid ? "chart-band chart-band--invalid" : "chart-band"}
            shape={bandShape(band.invalid, gapId, invalidId)}
          />
        ))}
        <Area
          dataKey="y"
          type="linear"
          connectNulls={false}
          dot={false}
          activeDot={false}
          stroke="none"
          fill={measuredColor}
          fillOpacity={0.2}
          isAnimationActive={false}
        />
        <Line
          className="chart-step"
          dataKey="y"
          type="linear"
          dot={false}
          activeDot={false}
          connectNulls={false}
          stroke={measuredColor}
          strokeWidth={2}
          strokeLinecap="square"
          isAnimationActive={false}
        />
        <ZeroMarks segments={model.segments} color={measuredColor} />
        <SelectionOutline segment={selected} />
      </ComposedChart>
    </ChartContainer>
  );
}
