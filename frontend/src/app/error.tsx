"use client";

/**
 * Unexpected errors only (spec 0010 AC-12). An unreachable API is handled
 * by `<ApiUnavailable>` in the page itself; production Next.js hides the
 * error class here, so only the `digest` is shown as a reference.
 */
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { en } from "@/messages/en";

type Props = {
  error: unknown;
  retry: () => void;
};

function digestOf(error: unknown): string | null {
  if (typeof error === "object" && error !== null && "digest" in error) {
    const { digest } = error as { digest?: unknown };
    return typeof digest === "string" ? digest : null;
  }
  return null;
}

export default function ErrorPage({ error, retry }: Props) {
  const digest = digestOf(error);
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Alert variant="destructive" className="max-w-md">
        <AlertTitle>{en.unexpected.message}</AlertTitle>
        <AlertDescription className="flex flex-col items-start gap-3">
          {digest && <span>{en.unexpected.reference(digest)}</span>}
          <Button type="button" variant="outline" onClick={() => retry()}>
            {en.unexpected.retry}
          </Button>
        </AlertDescription>
      </Alert>
    </main>
  );
}
