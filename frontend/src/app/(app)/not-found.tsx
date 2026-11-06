import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import Link from "next/link";

import { AppHeader } from "@/components/app/AppPage";
import { getServerQueryClient } from "@/lib/api/server";
import { en } from "@/messages/en";

/** One message: a foreign, archived, unknown, or malformed id all show it. */
export default function NotFound() {
  return (
    <HydrationBoundary state={dehydrate(getServerQueryClient())}>
      <AppHeader account />
      <main className="mx-auto flex w-full max-w-[1248px] flex-1 flex-col gap-3 px-4 py-10 sm:px-6">
        <h1 className="text-2xl leading-8 font-semibold">{en.notFound.title}</h1>
        <p className="text-sm leading-5">
          <Link href="/" className="text-primary underline underline-offset-4">
            {en.notFound.link}
          </Link>
        </p>
      </main>
    </HydrationBoundary>
  );
}
