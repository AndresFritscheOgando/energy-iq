/**
 * The accessible equivalent of the chart (spec 0011 child 0002 AC-6): measured
 * stretches and gaps merged, newest first. A gap says "No measured usage",
 * never a zero. The table scrolls in its own region on narrow screens.
 */
import type { TableRow } from "@/lib/consumption/chart-model";
import { en } from "@/messages/en";

import { SegmentGlyph } from "./SegmentGlyph";

export function IntervalsTable({
  rows,
  selectedKey,
}: {
  rows: readonly TableRow[];
  selectedKey: string | null;
}) {
  const columns = en.usage.columns;
  return (
    <section className="flex min-w-0 flex-col gap-3 min-[900px]:col-span-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="intervals-title" className="text-base leading-6 font-semibold">
          {en.usage.tableTitle}
        </h2>
        <span className="text-[13px] leading-5 text-muted-foreground">{en.usage.newestFirst}</span>
      </div>
      <div
        role="region"
        aria-labelledby="intervals-title"
        // A keyboard user must be able to scroll this region sideways.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        className="overflow-x-auto rounded-lg border bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <table className="w-full min-w-[640px] border-collapse text-left text-sm leading-5">
          <thead className="text-[13px] text-muted-foreground">
            <tr className="border-b">
              <th scope="col" className="px-4 py-2.5 font-medium">
                {columns.from}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {columns.to}
              </th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">
                {columns.length}
              </th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">
                {columns.kwh}
              </th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">
                {columns.rate}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {columns.note}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.key}
                data-kind={row.kind}
                className={`border-b last:border-b-0 ${row.key === selectedKey ? "bg-accent text-accent-foreground" : ""}`}
              >
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <span className="flex items-center gap-2">
                    <SegmentGlyph kind={row.kind} />
                    {row.from}
                  </span>
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap">{row.to}</td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">{row.length}</td>
                {row.kwh === null ? (
                  <td colSpan={2} className="px-4 py-2.5 text-center whitespace-nowrap">
                    {en.usage.noMeasured}
                  </td>
                ) : (
                  <>
                    <td className="px-4 py-2.5 text-right">{row.kwh}</td>
                    <td className="px-4 py-2.5 text-right">{row.rate}</td>
                  </>
                )}
                <td className="min-w-64 px-4 py-2.5 text-[13px]">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
