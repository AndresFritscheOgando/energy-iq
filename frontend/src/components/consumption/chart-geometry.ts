/**
 * The chart's fixed margins and y axis width (spec 0011 child 0002 AC-5). The
 * pointer maps x to time from these, so the wrapper and the Recharts drawing
 * must agree. Kept apart from `UsageChart` so that file can stay a lazy chunk.
 */
export const CHART_MARGIN = { top: 14, right: 8, bottom: 0, left: 0 } as const;
export const Y_AXIS_WIDTH = 36;

export function plotBounds(containerWidth: number): { left: number; width: number } {
  const left = CHART_MARGIN.left + Y_AXIS_WIDTH;
  return { left, width: Math.max(0, containerWidth - left - CHART_MARGIN.right) };
}
