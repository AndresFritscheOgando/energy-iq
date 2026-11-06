import { useId } from "react";

import type { SegmentKind } from "@/lib/consumption/chart-model";

/**
 * The small mark for each kind of segment, used by the legend and table. The
 * kinds differ by shape and texture, never only color (design README).
 */
export function SegmentGlyph({ kind }: { kind: SegmentKind }) {
  const id = useId();
  return (
    <svg aria-hidden="true" width="24" height="14" viewBox="0 0 24 14" className="shrink-0">
      {kind === "step" && (
        <>
          <rect x="0" y="2" width="24" height="12" fill="var(--chart-measured)" opacity="0.2" />
          <rect x="0" y="1" width="24" height="2" fill="var(--chart-measured)" />
        </>
      )}
      {kind === "zero" && (
        <>
          <rect x="0" y="11" width="24" height="3" fill="var(--chart-measured)" />
          <rect x="0" y="6" width="2" height="8" fill="var(--chart-measured)" />
          <rect x="22" y="6" width="2" height="8" fill="var(--chart-measured)" />
        </>
      )}
      {kind === "gap" && (
        <>
          <defs>
            <pattern
              id={id}
              patternUnits="userSpaceOnUse"
              width="6"
              height="6"
              patternTransform="rotate(45)"
            >
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--chart-gap)" strokeWidth="1.25" />
            </pattern>
          </defs>
          <rect width="24" height="14" fill={`url(#${id})`} />
        </>
      )}
      {kind === "invalid" && (
        <>
          <defs>
            <pattern
              id={id}
              patternUnits="userSpaceOnUse"
              width="8"
              height="8"
              patternTransform="rotate(45)"
            >
              <line x1="0" y1="0" x2="0" y2="8" stroke="var(--chart-invalid)" strokeWidth="1.25" />
              <line x1="0" y1="0" x2="8" y2="0" stroke="var(--chart-invalid)" strokeWidth="1.25" />
            </pattern>
          </defs>
          <rect y="3" width="24" height="11" fill={`url(#${id})`} />
          <path d="M8 0h8l-4 4z" fill="var(--chart-invalid)" />
        </>
      )}
    </svg>
  );
}
