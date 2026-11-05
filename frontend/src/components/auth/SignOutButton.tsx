"use client";

/**
 * Sign out (spec 0010 AC-9). On 204 the browser cache is cleared and the
 * page fully reloads at `/login`, so no in memory or router cached state
 * survives. On any failure the user stays signed in and sees why.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useLogout } from "@/lib/api/generated/auth/auth";
import { en } from "@/messages/en";

import { genericErrorMessage } from "./auth-errors";

type Props = {
  navigate?: (url: string) => void;
};

export function SignOutButton({ navigate = (url) => window.location.assign(url) }: Props) {
  const queryClient = useQueryClient();
  const logout = useLogout();
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const pending = logout.isPending || leaving;

  const signOut = async () => {
    if (pending) {
      return;
    }
    setError(null);
    try {
      await logout.mutateAsync();
    } catch (failure) {
      setError(genericErrorMessage(failure));
      return;
    }
    setLeaving(true);
    queryClient.clear();
    navigate("/login");
  };

  return (
    <div className="flex flex-col items-start gap-3">
      <Button type="button" variant="outline" onClick={signOut} disabled={pending}>
        {pending ? en.signOut.pending : en.signOut.submit}
      </Button>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
