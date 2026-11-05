"use client";

/**
 * Enter a reading (spec 0011 child 0001 AC-6 to AC-8). What is sent is what was
 * typed: nothing is rounded, trimmed, or converted. Client checks are for fast
 * feedback; the server's 422 and 409 are the authority.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type MouseEvent } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/app/FormField";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, ApiUnavailableError, isNotAuthenticated } from "@/lib/api/errors";
import { problemToForm, type FormErrors } from "@/lib/api/form-errors";
import { createReading, getListReadingsQueryOptions } from "@/lib/api/generated/default/default";
import { getGetMeterQueryKey } from "@/lib/api/generated/meters/meters";
import type { ReadingCreate, ReadingOut } from "@/lib/api/generated/model";
import { invalidateMeterData } from "@/lib/api/list-queries";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { compareDecimal, formatExact, parseDecimal } from "@/lib/decimal";
import { formatDateTime, formatLocalDate } from "@/lib/format";
import { localToday, zonedInstant, type ConsumptionWindow } from "@/lib/zoned-time";
import { en } from "@/messages/en";

const VALUE_FORMAT = /^[0-9]{1,12}(\.[0-9]{1,6})?$/;
const NOON = "12:00";

const schema = z.object({
  value: z.string().regex(VALUE_FORMAT, en.readingForm.valueFormat),
  date: z.string().min(1, en.readingForm.dateRequired),
  time: z.string(),
});
type Values = z.infer<typeof schema>;
type Name = keyof Values;

const FIELD_MAP = { cumulative_kwh: "value", local_date: "date", recorded_at: "time" } as const;
const FIELD_ORDER: readonly Name[] = ["value", "date", "time"];

type Problem = FormErrors<Name> & { inactive?: boolean; unavailable?: boolean };
const NO_PROBLEM: Problem = { fields: {}, form: null };

function toProblem(error: unknown): Problem {
  if (error instanceof ApiError && error.status === 409) {
    if (error.code === "reading_exists_at_instant") {
      return { fields: { date: en.readingForm.exists }, form: null };
    }
    if (error.code === "meter_inactive") {
      return { fields: {}, form: en.readingForm.inactiveBody, inactive: true };
    }
  }
  const mapped = problemToForm<Name>(error, FIELD_MAP);
  return error instanceof ApiUnavailableError ? { ...mapped, unavailable: true } : mapped;
}

function requestBody(values: Values, zone: string): ReadingCreate {
  return values.time
    ? {
        cumulative_kwh: values.value,
        recorded_at: zonedInstant(values.date, values.time, zone),
      }
    : { cumulative_kwh: values.value, local_date: values.date };
}

export function readingDate(
  reading: Pick<ReadingOut, "original_local_date" | "recorded_at">,
  zone: string,
  style: "long" | "medium",
): string {
  if (reading.original_local_date) {
    const plain = formatLocalDate(
      reading.original_local_date,
      style === "long" ? "date" : "mediumDate",
    );
    if (plain) {
      return plain;
    }
  }
  return (
    formatDateTime(reading.recorded_at, style === "long" ? "dateTime" : "mediumDateTime", zone) ??
    en.readings.notAvailable
  );
}

type Warning = { id: string; value: string; date: string };

type Props = {
  meterId: string;
  zone: string;
  /** From the server, so hydration can't mismatch. */
  today: string;
  window: ConsumptionWindow;
  /** The API said this meter is inactive; the page shows that from now on. */
  onInactive?: () => void;
};

export function ReadingForm({ meterId, zone, today: initialToday, window, onInactive }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const mutation = useMutation({
    mutationFn: ({ data, key }: { data: ReadingCreate; key: string }) =>
      createReading(meterId, data, { headers: { "Idempotency-Key": key } }),
  });

  const [today, setToday] = useState(initialToday);
  const [problem, setProblem] = useState(NO_PROBLEM);
  const [warning, setWarning] = useState<Warning | null>(null);
  const [saved, setSaved] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);
  const warningRef = useRef<HTMLDivElement>(null);
  const warningFocusFrame = useRef<number | null>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { value: "", date: initialToday, time: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const pending = isSubmitting || mutation.isPending;
  const locked = problem.inactive === true;

  const message = (name: Name) => errors[name]?.message ?? problem.fields[name];

  const clearMessages = () => {
    if (warningFocusFrame.current !== null) {
      cancelAnimationFrame(warningFocusFrame.current);
      warningFocusFrame.current = null;
    }
    setWarning(null);
    setSaved(false);
    setProblem(NO_PROBLEM);
  };

  const refreshToday = () => setToday(localToday(zone));

  /** The nearest earlier valid reading when the entered value is below it. */
  const lowerThanEarlier = async (values: Values): Promise<Warning | "session_lost" | null> => {
    const entered = parseDecimal(values.value);
    const to = zonedInstant(values.date, values.time || NOON, zone);
    try {
      const page = await queryClient.fetchQuery(
        getListReadingsQueryOptions(
          meterId,
          { order: "desc", to, status: "valid", limit: 1 },
          { query: { staleTime: 0, retry: false } },
        ),
      );
      const earlier = page.items[0];
      const parsed = earlier ? parseDecimal(earlier.cumulative_kwh) : null;
      if (!earlier || !parsed || !entered || compareDecimal(entered, parsed) >= 0) {
        return null;
      }
      return {
        id: earlier.id,
        value: formatExact(parsed),
        date: readingDate(earlier, zone, "long"),
      };
    } catch (error) {
      // Fail open: the API preserves the value and the chart reports it.
      return isNotAuthenticated(error) ? "session_lost" : null;
    }
  };

  const save = async (values: Values) => {
    const data = requestBody(values, zone);
    const key = idempotency.keyFor(JSON.stringify(data));
    let reading: ReadingOut;
    try {
      reading = await mutation.mutateAsync({ data, key });
    } catch (error) {
      const found = toProblem(error);
      setProblem(found);
      if (found.inactive) {
        onInactive?.();
        void queryClient.invalidateQueries({ queryKey: getGetMeterQueryKey(meterId) });
      }
      const first = FIELD_ORDER.find((name) => found.fields[name]);
      if (first) {
        form.setFocus(first);
      } else {
        requestAnimationFrame(() => alertRef.current?.focus());
      }
      return;
    }
    idempotency.reset();
    setWarning(null);
    form.reset({ value: "", date: values.date, time: "" });
    setSaved(true);
    // After the reset renders and the disabled submit button has let go of focus.
    requestAnimationFrame(() => form.setFocus("value"));
    void invalidateMeterData(queryClient, meterId);
    if (Date.parse(reading.recorded_at) >= Date.parse(window.to)) {
      // The page sat open past midnight: only the server can move the window.
      router.refresh();
    }
  };

  const submit = async (values: Values) => {
    if (mutation.isPending) {
      return;
    }
    refreshToday();
    clearMessages();
    const lower = await lowerThanEarlier(values);
    if (lower === "session_lost") {
      return; // The global handler is already navigating to login.
    }
    if (lower) {
      setWarning(lower);
      const frame = requestAnimationFrame(() => {
        if (warningFocusFrame.current === frame) {
          warningFocusFrame.current = null;
          warningRef.current?.focus();
        }
      });
      warningFocusFrame.current = frame;
      return;
    }
    await save(values);
  };

  const showEarlierReading = (event: MouseEvent<HTMLAnchorElement>) => {
    const row = warning && document.getElementById(`reading-${warning.id}`);
    if (row) {
      event.preventDefault();
      if (warningFocusFrame.current !== null) {
        cancelAnimationFrame(warningFocusFrame.current);
        warningFocusFrame.current = null;
      }
      row.scrollIntoView({ block: "center" });
      row.focus();
    }
  };

  return (
    <form
      id="reading-form"
      method="post"
      noValidate
      aria-labelledby="reading-form-title"
      onSubmit={(event) => void form.handleSubmit(submit)(event)}
      className="flex flex-col gap-4 rounded-lg border bg-card p-5"
    >
      <h2 id="reading-form-title" className="text-base leading-6 font-semibold">
        {en.readingForm.title}
      </h2>

      <FormField
        id="reading-value"
        label={en.readingForm.value}
        labelNote={en.readingForm.valueUnit}
        hint={en.readingForm.valueHint}
        error={message("value")}
      >
        {(aria) => (
          <Input
            type="text"
            inputMode="decimal"
            autoComplete="off"
            disabled={locked}
            {...aria}
            {...form.register("value", { onChange: clearMessages })}
          />
        )}
      </FormField>

      <div className="grid grid-cols-2 gap-3">
        <FormField id="reading-date" label={en.readingForm.date} error={message("date")}>
          {(aria) => (
            <Input
              type="date"
              max={today}
              disabled={locked}
              onFocus={refreshToday}
              {...aria}
              {...form.register("date", { onChange: clearMessages })}
            />
          )}
        </FormField>
        <FormField
          id="reading-time"
          label={en.readingForm.time}
          labelNote={en.optional}
          error={message("time")}
        >
          {(aria) => (
            <Input
              type="time"
              disabled={locked}
              {...aria}
              {...form.register("time", { onChange: clearMessages })}
            />
          )}
        </FormField>
      </div>

      {warning && (
        <div
          ref={warningRef}
          role="alert"
          tabIndex={-1}
          className="flex gap-2.5 rounded-lg border border-warning bg-warning/10 p-3 text-sm leading-5 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="flex min-w-0 flex-col gap-2">
            <p className="font-semibold text-warning-foreground">{en.readingForm.warningTitle}</p>
            <p>
              {en.readingForm.warningBefore}{" "}
              <a
                href={`#reading-${warning.id}`}
                onClick={showEarlierReading}
                className="text-primary underline underline-offset-4"
              >
                {en.readingForm.warningLink(warning.value, warning.date)}
              </a>
              . {en.readingForm.warningAfter}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" disabled={pending} onClick={() => void save(form.getValues())}>
                {mutation.isPending ? en.readingForm.pending : en.readingForm.saveAnyway}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={() => {
                  setWarning(null);
                  form.setFocus("value");
                }}
              >
                {en.readingForm.changeValue}
              </Button>
            </div>
          </div>
        </div>
      )}

      {problem.form && (
        <Alert variant="destructive" ref={alertRef} tabIndex={-1}>
          {(problem.inactive || problem.unavailable) && (
            <AlertTitle className="text-foreground">
              {problem.inactive ? en.readingForm.inactiveTitle : en.unavailable.message}
            </AlertTitle>
          )}
          <AlertDescription>
            {problem.unavailable ? en.readingForm.notSaved : problem.form}
          </AlertDescription>
        </Alert>
      )}

      {!warning && (
        <Button type="submit" disabled={pending || locked} className="w-full">
          {pending ? en.readingForm.pending : en.readingForm.submit}
        </Button>
      )}

      <p
        role="status"
        className="flex min-h-5 items-center gap-2 text-[13px] leading-5 empty:hidden"
      >
        {saved && (
          <>
            <CircleCheck aria-hidden="true" className="size-4 text-primary" />
            {en.readingForm.saved}
          </>
        )}
      </p>
    </form>
  );
}
