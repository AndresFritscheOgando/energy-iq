"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { en } from "@/messages/en";

/** Reruns the server render of the current page (spec 0010 AC-12). */
export function RetryButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      type="button"
      variant="outline"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      {pending ? en.unavailable.retrying : en.unavailable.retry}
    </Button>
  );
}
