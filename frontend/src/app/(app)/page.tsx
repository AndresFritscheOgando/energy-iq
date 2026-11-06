import { AppPage, UnavailablePage } from "@/components/app/AppPage";
import { CreatePropertyForm } from "@/components/properties/CreatePropertyForm";
import { MemberSince } from "@/components/properties/MemberSince";
import { PropertyList } from "@/components/properties/PropertyList";
import { propertiesListOptions } from "@/lib/api/list-queries";
import { getServerQueryClient, requireSession, serverRequestInit } from "@/lib/api/server";
import { en } from "@/messages/en";

const PATH = "/";

export default async function HomePage({ searchParams }: PageProps<"/">) {
  const session = await requireSession(PATH, await searchParams);
  if (session.status === "unavailable") {
    return <UnavailablePage requestId={session.requestId} />;
  }

  // May fail: a failed prefetch stays out of the hydrated cache, so the browser fetches.
  const server = await serverRequestInit();
  await getServerQueryClient().prefetchInfiniteQuery(propertiesListOptions({ server }));

  return (
    <AppPage breadcrumb={[{ label: en.home.breadcrumb }]} title={en.home.title}>
      <PropertyList />
      <CreatePropertyForm />
      <MemberSince />
    </AppPage>
  );
}
