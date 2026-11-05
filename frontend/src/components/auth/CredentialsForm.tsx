"use client";

/**
 * The sign in and sign up form (spec 0010 AC-7, AC-8, AC-15).
 *
 * The client only checks that both fields are filled; the server's 422 is
 * the authority. On a failed submit, focus moves to the first invalid field,
 * or to the form alert when no field is invalid.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useLogin, useRegister } from "@/lib/api/generated/auth/auth";
import { en } from "@/messages/en";

import { authProblem, type CredentialField, type FormProblem } from "./auth-errors";

export type CredentialsMode = "login" | "register";

const notBlank = (message: string) =>
  z.string().refine((value) => value.trim().length > 0, { message });

const schema = z.object({
  email: notBlank(en.required.email),
  password: notBlank(en.required.password),
});

type Values = z.infer<typeof schema>;

const FIELD_ORDER: readonly CredentialField[] = ["email", "password"];

/** Password length as the backend counts it (NFKC code points). */
export function passwordLength(value: string): number {
  return [...value.normalize("NFKC")].length;
}

type Props = {
  mode: CredentialsMode;
  /** Where to go after success; already passed through `safeNextPath`. */
  next: string;
};

export function CredentialsForm({ mode, next }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const login = useLogin();
  const register = useRegister();
  const mutation = mode === "login" ? login : register;
  const copy = mode === "login" ? en.login : en.register;

  const [problem, setProblem] = useState<FormProblem>({ fields: {}, form: null });
  const [succeeded, setSucceeded] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;
  // `useWatch` (not `watch`) so the React Compiler can memoize this form.
  const password = useWatch({ control: form.control, name: "password" });
  const pending = isSubmitting || mutation.isPending || succeeded;

  const fieldMessage = (name: CredentialField) =>
    errors[name]?.message ?? problem.fields[name]?.message;

  const submitValues = async (values: Values) => {
    if (mutation.isPending) {
      return;
    }
    setProblem({ fields: {}, form: null });
    try {
      await mutation.mutateAsync({ data: values });
    } catch (error) {
      const found = authProblem(error, mode);
      setProblem(found);
      const first = FIELD_ORDER.find((name) => found.fields[name]);
      if (first) {
        form.setFocus(first);
      } else {
        // Wait for the alert to render before moving focus to it.
        requestAnimationFrame(() => alertRef.current?.focus());
      }
      return;
    }
    setSucceeded(true);
    queryClient.clear();
    router.replace(mode === "login" ? next : "/");
  };

  const describedBy = (name: CredentialField, extra?: string) =>
    [extra, fieldMessage(name) ? `${mode}-${name}-error` : undefined].filter(Boolean).join(" ") ||
    undefined;

  const hintId = `${mode}-password-hint`;

  return (
    <form
      method="post"
      noValidate
      onSubmit={(event) => void form.handleSubmit(submitValues)(event)}
      aria-labelledby={`${mode}-title`}
    >
      <FieldGroup>
        {problem.form && (
          <Alert variant="destructive" ref={alertRef} tabIndex={-1}>
            <AlertDescription>{problem.form}</AlertDescription>
          </Alert>
        )}

        <Field data-invalid={Boolean(fieldMessage("email")) || undefined}>
          <FieldLabel htmlFor={`${mode}-email`}>{en.fields.email}</FieldLabel>
          <Input
            id={`${mode}-email`}
            type="email"
            autoComplete="email"
            aria-invalid={Boolean(fieldMessage("email"))}
            aria-describedby={describedBy("email")}
            {...form.register("email")}
          />
          {fieldMessage("email") && (
            <FieldError id={`${mode}-email-error`}>
              {fieldMessage("email")}
              {problem.fields.email?.emailTaken && !errors.email && (
                <>
                  {" "}
                  <Link href="/login" className="underline underline-offset-4">
                    {en.register.signInInstead}
                  </Link>
                </>
              )}
            </FieldError>
          )}
        </Field>

        <Field data-invalid={Boolean(fieldMessage("password")) || undefined}>
          <FieldLabel htmlFor={`${mode}-password`}>{en.fields.password}</FieldLabel>
          <Input
            id={`${mode}-password`}
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            aria-invalid={Boolean(fieldMessage("password"))}
            aria-describedby={describedBy("password", mode === "register" ? hintId : undefined)}
            {...form.register("password")}
          />
          {mode === "register" && (
            <FieldDescription id={hintId}>
              {en.register.passwordHint(passwordLength(password))}
            </FieldDescription>
          )}
          {fieldMessage("password") && (
            <FieldError id={`${mode}-password-error`}>{fieldMessage("password")}</FieldError>
          )}
        </Field>

        <Button type="submit" disabled={pending} aria-disabled={pending}>
          {pending ? copy.pending : copy.submit}
        </Button>
      </FieldGroup>
    </form>
  );
}
