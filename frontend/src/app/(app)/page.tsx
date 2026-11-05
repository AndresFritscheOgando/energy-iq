import { dehydrate, HydrationBoundary } from "@tanstack/react-query";

import { ApiUnavailable } from "@/components/ApiUnavailable";
import { HomeContent } from "@/components/HomeContent";
import { getServerQueryClient, requireSession } from "@/lib/api/server";
import { en } from "@/messages/en";

const PATH = "/";

export default async function HomePage({ searchParams }: PageProps<"/">) {
  const session = await requireSession(PATH, await searchParams);
  if (session.status === "unavailable") {
    return <ApiUnavailable requestId={session.requestId} />;
  }

  return (
    <div className="flex max-w-xl flex-col gap-6">
      <h1 className="font-heading text-2xl font-semibold">{en.home.title}</h1>
      <HydrationBoundary state={dehydrate(getServerQueryClient())}>
        <HomeContent />
      </HydrationBoundary>
    </div>
  );
}
