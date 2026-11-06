"use client";

/** Create a property, then open its page (spec 0011 child 0001 AC-3). */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/app/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import { problemToForm, type FormErrors } from "@/lib/api/form-errors";
import {
  createProperty,
  getListPropertiesQueryKey,
} from "@/lib/api/generated/properties/properties";
import { useIdempotencyKey } from "@/lib/api/use-idempotency-key";
import { en } from "@/messages/en";

const schema = z.object({
  nickname: z.string().refine((value) => value.trim().length > 0, {
    message: en.propertyForm.nicknameRequired,
  }),
  region: z.string(),
});
type Values = z.infer<typeof schema>;
type Name = keyof Values;

const FIELD_MAP = { nickname: "nickname", region: "region" } as const;
const FIELD_ORDER: readonly Name[] = ["nickname", "region"];
const NO_PROBLEM: FormErrors<Name> = { fields: {}, form: null };

function toProblem(error: unknown): FormErrors<Name> {
  if (error instanceof ApiError && error.status === 409 && error.code === "property_name_taken") {
    return { fields: { nickname: en.propertyForm.nameTaken }, form: null };
  }
  return problemToForm<Name>(error, FIELD_MAP);
}

export function CreatePropertyForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const mutation = useMutation({
    mutationFn: ({ data, key }: { data: Parameters<typeof createProperty>[0]; key: string }) =>
      createProperty(data, { headers: { "Idempotency-Key": key } }),
  });
  const [problem, setProblem] = useState(NO_PROBLEM);
  const [succeeded, setSucceeded] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { nickname: "", region: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const pending = isSubmitting || mutation.isPending || succeeded;

  const message = (name: Name) => errors[name]?.message ?? problem.fields[name];

  const submit = async (values: Values) => {
    if (mutation.isPending) {
      return;
    }
    setProblem(NO_PROBLEM);
    const region = values.region.trim();
    const data = { nickname: values.nickname, ...(region ? { region } : {}) };
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
    void queryClient.invalidateQueries({ queryKey: getListPropertiesQueryKey() });
    router.push(`/properties/${id}`);
  };

  return (
    <form
      method="post"
      noValidate
      aria-labelledby="create-property-title"
      onSubmit={(event) => void form.handleSubmit(submit)(event)}
      className="flex flex-col gap-4 rounded-lg border bg-card p-5"
    >
      <h2 id="create-property-title" className="text-base leading-6 font-semibold">
        {en.propertyForm.title}
      </h2>
      {problem.form && (
        <Alert variant="destructive" ref={alertRef} tabIndex={-1}>
          <AlertDescription>{problem.form}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <FormField
          id="property-nickname"
          label={en.propertyForm.nickname}
          hint={en.propertyForm.nicknameHint}
          error={message("nickname")}
          className="sm:flex-[1.2]"
        >
          {(aria) => <Input autoComplete="off" {...aria} {...form.register("nickname")} />}
        </FormField>
        <FormField
          id="property-region"
          label={en.propertyForm.region}
          labelNote={en.optional}
          error={message("region")}
          className="sm:flex-1"
        >
          {(aria) => <Input autoComplete="off" {...aria} {...form.register("region")} />}
        </FormField>
        <Button type="submit" disabled={pending} className="sm:mt-[1.625rem]">
          {pending ? en.propertyForm.pending : en.propertyForm.submit}
        </Button>
      </div>
    </form>
  );
}
