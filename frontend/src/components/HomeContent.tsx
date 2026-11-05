"use client";

/**
 * The signed in home panel. `useMe()` reads the `/auth/me` result the
 * server prefetched and hydrated, so the first load makes no browser
 * request for it (spec 0010 AC-5, AC-16).
 */
import { SignOutButton } from "@/components/auth/SignOutButton";
import { useMe } from "@/lib/api/generated/auth/auth";
import { formatDateTime } from "@/lib/format";
import { en } from "@/messages/en";

export function HomeContent() {
  const { data: user } = useMe();
  if (!user) {
    return null;
  }
  const since = formatDateTime(user.created_at, "date");

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p className="text-base">{en.home.signedInAs(user.email)}</p>
        {since && <p className="text-sm text-muted-foreground">{en.home.memberSince(since)}</p>}
      </div>
      <SignOutButton />
    </section>
  );
}
