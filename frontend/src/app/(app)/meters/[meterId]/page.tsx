import { AppPage, UnavailablePage } from "@/components/app/AppPage";
import { MeterScreen, MeterTitleAside } from "@/components/readings/MeterScreen";
import { getStoredConsumptionQueryOptions } from "@/lib/api/generated/default/default";
import { getGetMeterQueryOptions } from "@/lib/api/generated/meters/meters";
import type { MeterOut, PropertyOut } from "@/lib/api/generated/model";
import { getGetPropertyQueryOptions } from "@/lib/api/generated/properties/properties";
import { readingsListOptions } from "@/lib/api/list-queries";
import {
  getServerQueryClient,
  loadOrNotFound,
  requireSession,
  serverRequestInit,
} from "@/lib/api/server";
import { localToday, parseRange, windowFor } from "@/lib/zoned-time";
import { en } from "@/messages/en";

/** A slow chart can't hold up the page by more than this (child 0002 AC-10). */
const CONSUMPTION_TIMEOUT_MS = 2_000;

export default async function MeterPage({ params, searchParams }: PageProps<"/meters/[meterId]">) {
  const { meterId } = await params;
  const query = await searchParams;
  const path = `/meters/${meterId}`;
  const session = await requireSession(path, query);
  if (session.status === "unavailable") {
    return <UnavailablePage requestId={session.requestId} />;
  }

  const server = await serverRequestInit();
  const meter = await loadOrNotFound<MeterOut>(
    getGetMeterQueryOptions(meterId, { request: { server } }),
    path,
    query,
  );
  if (meter.status === "unavailable") {
    return <UnavailablePage requestId={meter.requestId} />;
  }
  const property = await loadOrNotFound<PropertyOut>(
    getGetPropertyQueryOptions(meter.data.property_id, { request: { server } }),
    path,
    query,
  );
  if (property.status === "unavailable") {
    return <UnavailablePage requestId={property.requestId} />;
  }

  const zone = property.data.timezone;
  const range = parseRange(query.range);
  const now = new Date();
  const window = windowFor(range, zone, now);

  const client = getServerQueryClient();
  await Promise.all([
    client.prefetchInfiniteQuery(readingsListOptions(meterId, { server })),
    client.prefetchQuery(
      getStoredConsumptionQueryOptions(meterId, window, {
        request: { server: { ...server, timeoutMs: CONSUMPTION_TIMEOUT_MS } },
      }),
    ),
  ]);

  const { label, distributor, property_id: propertyId } = meter.data;
  const { nickname } = property.data;
  return (
    <AppPage
      breadcrumb={[
        { label: en.home.breadcrumb, href: "/" },
        { label: nickname, href: `/properties/${propertyId}` },
        { label },
      ]}
      title={label}
      titleAside={
        <MeterTitleAside
          meterId={meterId}
          subtitle={`${en.meterForm.distributorLabels[distributor]}, ${nickname}`}
        />
      }
    >
      <MeterScreen
        meterId={meterId}
        zone={zone}
        today={localToday(zone, now)}
        range={range}
        window={window}
      />
    </AppPage>
  );
}
