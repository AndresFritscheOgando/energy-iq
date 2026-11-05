import { AppPage, UnavailablePage } from "@/components/app/AppPage";
import { CreateMeterForm } from "@/components/meters/CreateMeterForm";
import { MeterList } from "@/components/meters/MeterList";
import type { PropertyOut } from "@/lib/api/generated/model";
import { getGetPropertyQueryOptions } from "@/lib/api/generated/properties/properties";
import { metersListOptions } from "@/lib/api/list-queries";
import {
  getServerQueryClient,
  loadOrNotFound,
  requireSession,
  serverRequestInit,
} from "@/lib/api/server";
import { en } from "@/messages/en";

export default async function PropertyPage({
  params,
  searchParams,
}: PageProps<"/properties/[propertyId]">) {
  const { propertyId } = await params;
  const query = await searchParams;
  const path = `/properties/${propertyId}`;
  const session = await requireSession(path, query);
  if (session.status === "unavailable") {
    return <UnavailablePage requestId={session.requestId} />;
  }

  const server = await serverRequestInit();
  const property = await loadOrNotFound<PropertyOut>(
    getGetPropertyQueryOptions(propertyId, { request: { server } }),
    path,
    query,
  );
  if (property.status === "unavailable") {
    return <UnavailablePage requestId={property.requestId} />;
  }
  await getServerQueryClient().prefetchInfiniteQuery(metersListOptions(propertyId, { server }));

  const { nickname, region } = property.data;
  return (
    <AppPage
      breadcrumb={[{ label: en.home.breadcrumb, href: "/" }, { label: nickname }]}
      title={nickname}
      titleAside={
        region ? (
          <span className="text-[13px] leading-5 text-muted-foreground">{region}</span>
        ) : null
      }
    >
      <section aria-labelledby="meters-title" className="flex flex-col gap-3">
        <h2 id="meters-title" className="text-base leading-6 font-semibold">
          {en.property.metersTitle}
        </h2>
        <MeterList propertyId={propertyId} />
      </section>
      <CreateMeterForm propertyId={propertyId} />
    </AppPage>
  );
}
