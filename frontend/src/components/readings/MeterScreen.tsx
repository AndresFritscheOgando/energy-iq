"use client";

/**
 * The meter page's body (spec 0011). One column under 900 px with the form
 * first, which is also first in the DOM, so tab order matches at every width.
 */
import { useState } from "react";

import { UsageSection } from "@/components/consumption/UsageSection";
import { useGetMeter } from "@/lib/api/generated/meters/meters";
import type { ConsumptionWindow, Range } from "@/lib/zoned-time";
import { en } from "@/messages/en";

import { ReadingForm } from "./ReadingForm";
import { ReadingsList } from "./ReadingsList";

type Props = {
  meterId: string;
  zone: string;
  today: string;
  range: Range;
  window: ConsumptionWindow;
};

export function MeterScreen({ meterId, zone, today, range, window }: Props) {
  const { data: meter } = useGetMeter(meterId);
  // Keep the form, with its alert, after the API says the meter went inactive.
  const [formSawInactive, setFormSawInactive] = useState(false);
  const active = meter?.active !== false;

  return (
    <div className="grid grid-cols-1 gap-6 min-[900px]:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-[900px]:col-start-2 min-[900px]:row-start-1">
        {active || formSawInactive ? (
          <ReadingForm
            meterId={meterId}
            zone={zone}
            today={today}
            window={window}
            onInactive={() => setFormSawInactive(true)}
          />
        ) : (
          <div className="rounded-lg border bg-card p-5">
            <h2 className="text-base leading-6 font-semibold">{en.inactiveMeter.title}</h2>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {en.inactiveMeter.body}
            </p>
          </div>
        )}
      </div>
      <UsageSection
        meterId={meterId}
        zone={zone}
        range={range}
        window={window}
        canAddReadings={active}
      />
      <ReadingsList meterId={meterId} zone={zone} />
    </div>
  );
}

/** The marker beside the title; follows a refetched meter. */
export function MeterTitleAside({ meterId, subtitle }: { meterId: string; subtitle: string }) {
  const { data: meter } = useGetMeter(meterId);
  return (
    <>
      {meter?.active === false && (
        <span className="self-center rounded-full border bg-muted px-2 py-0.5 text-xs leading-4 text-muted-foreground">
          {en.inactiveMeter.marker}
        </span>
      )}
      <span className="text-[13px] leading-5 text-muted-foreground">{subtitle}</span>
    </>
  );
}
