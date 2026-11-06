"use client";

/** Create a meter, then open its page (spec 0011 child 0001 AC-5). */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/app/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { ApiError } from "@/lib/api/errors";
import { problemToForm, type FormErrors } from "@/lib/api/form-errors";
import { createMeter, getListMetersQueryKey } from "@/lib/api/generated/meters/meters";
import { Distributor } from "@/lib/api/generated/model";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { en } from "@/messages/en";

const schema = z.object({
  label: z.string().refine((value) => value.trim().length > 0, {
    message: en.meterForm.labelRequired,
  }),
  distributor: z.string().refine((value) => value in Distributor, {
    message: en.meterForm.distributorRequired,
  }),
});
type Values = z.infer<typeof schema>;
type Name = keyof Values;

const FIELD_MAP = { label: "label", distributor: "distributor" } as const;
const FIELD_ORDER: readonly Name[] = ["label", "distributor"];
type Problem = FormErrors<Name> & { propertyGone?: boolean };
const NO_PROBLEM: Problem = { fields: {}, form: null };

function toProblem(error: unknown): Problem {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === "meter_label_taken") {
      return { fields: { label: en.meterForm.labelTaken }, form: null };
    }
    if (error.status === 404) {
      return { fields: {}, form: en.meterForm.propertyGone, propertyGone: true };
    }
  }
  return problemToForm<Name>(error, FIELD_MAP);
}

export function CreateMeterForm({ propertyId }: { propertyId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const mutation = useMutation({
    mutationFn: ({ data, key }: { data: Parameters<typeof createMeter>[1]; key: string }) =>
      createMeter(propertyId, data, { headers: { "Idempotency-Key": key } }),
  });
  const [problem, setProblem] = useState(NO_PROBLEM);
  const [succeeded, setSucceeded] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { label: "", distributor: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const pending = isSubmitting || mutation.isPending || succeeded;

  const message = (name: Name) => errors[name]?.message ?? problem.fields[name];

  const submit = async (values: Values) => {
    if (mutation.isPending) {
      return;
    }
    setProblem(NO_PROBLEM);
    const data = { label: values.label, distributor: values.distributor as Distributor };
    const key = idempotency.keyFor(JSON.stringify(data));
    let id: string;
    try {
      ({ id } = await mutation.mutateAsync({ data, key }));
    } catch (error) {
      const found = toProblem(error);
      setProblem(found);
      const first = FIELD_ORDER.find((name) => found.fields[name]);
      if (first) {
        form.setFocus(first);
      } else {
        requestAnimationFrame(() => alertRef.current?.focus());
      }
      return;
    }
    idempotency.reset();
    setSucceeded(true);
    void queryClient.invalidateQueries({ queryKey: getListMetersQueryKey(propertyId) });
    router.push(`/meters/${id}`);
  };

  return (
    <form
      method="post"
      noValidate
      aria-labelledby="create-meter-title"
      onSubmit={(event) => void form.handleSubmit(submit)(event)}
      className="flex flex-col gap-4 rounded-lg border bg-card p-5"
    >
      <h2 id="create-meter-title" className="text-base leading-6 font-semibold">
        {en.meterForm.title}
      </h2>
      {problem.form && (
        <Alert variant="destructive" ref={alertRef} tabIndex={-1}>
          <AlertDescription>
            {problem.form}
            {problem.propertyGone && (
              <>
                {" "}
                <Link href="/" className="underline underline-offset-4">
                  {en.meterForm.goHome}
                </Link>
              </>
            )}
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <FormField
          id="meter-label"
          label={en.meterForm.label}
          hint={en.meterForm.labelHint}
          error={message("label")}
          className="sm:flex-[1.2]"
        >
          {(aria) => <Input autoComplete="off" {...aria} {...form.register("label")} />}
        </FormField>
        <FormField
          id="meter-distributor"
          label={en.meterForm.distributor}
          error={message("distributor")}
          className="sm:flex-1"
        >
          {(aria) => (
            <NativeSelect {...aria} {...form.register("distributor")}>
              <option value="">{en.meterForm.distributorPlaceholder}</option>
              {Object.values(Distributor).map((value) => (
                <option key={value} value={value}>
                  {en.meterForm.distributorLabels[value]}
                </option>
              ))}
            </NativeSelect>
          )}
        </FormField>
        <Button type="submit" disabled={pending} className="sm:mt-[1.625rem]">
          {pending ? en.meterForm.pending : en.meterForm.submit}
        </Button>
      </div>
    </form>
  );
}
