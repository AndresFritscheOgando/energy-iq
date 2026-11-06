"use client";

import { SignOutButton } from "@/components/auth/SignOutButton";
import { useMe } from "@/lib/api/generated/auth/auth";

/** Email and sign out, from the `/auth/me` result the server hydrated. */
export function AccountControls() {
  const { data: user } = useMe();
  if (!user) {
    return null;
  }
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="truncate text-[13px] leading-5 text-muted-foreground">{user.email}</span>
      <SignOutButton />
    </div>
  );
}
