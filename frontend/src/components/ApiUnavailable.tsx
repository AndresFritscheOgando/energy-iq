/**
 * Shown when a server render cannot reach FastAPI (spec 0010 AC-12). A
 * server component, because production Next.js hides the error class from
 * `error.tsx`; `requireSession` and every prefetch render this themselves.
 */
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { en } from "@/messages/en";

import { RetryButton } from "./RetryButton";

type Props = {
  requestId: string | null;
};

export function ApiUnavailable({ requestId }: Props) {
  return (
    <Alert variant="destructive" className="max-w-md">
      <AlertTitle>{en.unavailable.message}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        {requestId && <span>{en.unavailable.reference(requestId)}</span>}
        <RetryButton />
      </AlertDescription>
    </Alert>
  );
}
