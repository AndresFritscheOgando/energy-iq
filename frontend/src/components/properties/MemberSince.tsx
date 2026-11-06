"use client";

import { useMe } from "@/lib/api/generated/auth/auth";
import { formatDateTime } from "@/lib/format";
import { en } from "@/messages/en";

/** "Member since", from the hydrated `/auth/me` (spec 0010 AC-16). */
export function MemberSince() {
  const { data: user } = useMe();
  const since = user ? formatDateTime(user.created_at, "date") : null;
  return since ? (
    <p className="text-[13px] leading-5 text-muted-foreground">{en.home.memberSince(since)}</p>
  ) : null;
}
