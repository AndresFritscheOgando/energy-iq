/**
 * Map an auth API error to what the form shows (spec 0010 AC-7, AC-8, AC-12).
 * Copy always comes from `en.ts`; the server's `message` is never shown.
 */
import { ApiError } from "@/lib/api/errors";
import { genericErrorMessage, problemToForm, suggestedDevOrigin } from "@/lib/api/form-errors";
import { en } from "@/messages/en";

export { genericErrorMessage, suggestedDevOrigin };

export type CredentialField = "email" | "password";

export type FieldProblem = { message: string; emailTaken?: boolean };

export type FormProblem = {
  fields: Partial<Record<CredentialField, FieldProblem>>;
  form: string | null;
};

const CREDENTIAL_FIELDS = { email: "email", password: "password" } as const;

export function minutesToWait(retryAfterSeconds: number | null): number | null {
  if (retryAfterSeconds === null || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds < 0) {
    return null;
  }
  return Math.max(1, Math.ceil(retryAfterSeconds / 60));
}

function validationProblem(error: ApiError): FormProblem {
  const { fields, form } = problemToForm<CredentialField>(error, CREDENTIAL_FIELDS);
  const mapped: FormProblem["fields"] = {};
  for (const name of Object.keys(fields) as CredentialField[]) {
    mapped[name] = { message: fields[name] as string };
  }
  return { fields: mapped, form };
}

export function authProblem(error: unknown, operation: "login" | "register"): FormProblem {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return validationProblem(error);
    }
    if (error.status === 429 && error.code === "too_many_attempts") {
      return { fields: {}, form: en.tooManyAttempts(minutesToWait(error.retryAfterSeconds)) };
    }
    if (operation === "login" && error.status === 401 && error.code === "invalid_credentials") {
      return { fields: {}, form: en.login.invalidCredentials };
    }
    if (operation === "register" && error.status === 409 && error.code === "email_taken") {
      return {
        fields: { email: { message: en.register.emailTaken, emailTaken: true } },
        form: null,
      };
    }
  }
  return { fields: {}, form: genericErrorMessage(error) };
}
