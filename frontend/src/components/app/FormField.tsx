import type { ReactNode } from "react";

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";

/** What a form control spreads on itself to be tied to its label and messages. */
export type ControlAria = {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
};

type Props = {
  id: string;
  label: string;
  /** Quiet text beside the label, like "(optional)". */
  labelNote?: string;
  hint?: string;
  error?: string;
  /** Extra content inside the error, like a link. */
  errorExtra?: ReactNode;
  className?: string;
  children: (aria: ControlAria) => ReactNode;
};

/** The `CredentialsForm` conventions as one piece (spec 0011 child 0001 AC-12). */
export function FormField({
  id,
  label,
  labelNote,
  hint,
  error,
  errorExtra,
  className,
  children,
}: Props) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <Field data-invalid={Boolean(error) || undefined} className={className}>
      <FieldLabel htmlFor={id}>
        {label}
        {labelNote && <span className="font-normal text-muted-foreground">{labelNote}</span>}
      </FieldLabel>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {hint && <FieldDescription id={hintId}>{hint}</FieldDescription>}
      {error && (
        <FieldError id={errorId}>
          {error}
          {errorExtra}
        </FieldError>
      )}
    </Field>
  );
}
