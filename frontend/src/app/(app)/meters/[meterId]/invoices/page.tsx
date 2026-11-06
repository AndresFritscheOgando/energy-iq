import { AppPage, UnavailablePage } from "@/components/app/AppPage";
import { InvoiceListScreen } from "@/components/invoices/InvoiceListScreen";
import { getGetMeterQueryOptions } from "@/lib/api/generated/meters/meters";
import type { MeterOut, PropertyOut } from "@/lib/api/generated/model";
import { getGetPropertyQueryOptions } from "@/lib/api/generated/properties/properties";
import { loadOrNotFound, requireSession, serverRequestInit } from "@/lib/api/server";
import { en } from "@/messages/en";

export default async function MeterInvoicesPage({
  params,
  searchParams,
}: PageProps<"/meters/[meterId]/invoices">) {
  const { meterId } = await params;
  const query = await searchParams;
  const path = `/meters/${meterId}/invoices`;
  const session = await requireSession(path, query);
  if (session.status === "unavailable") return <UnavailablePage requestId={session.requestId} />;

  const server = await serverRequestInit();
  const meter = await loadOrNotFound<MeterOut>(
    getGetMeterQueryOptions(meterId, { request: { server } }),
    path,
    query,
  );
  if (meter.status === "unavailable") return <UnavailablePage requestId={meter.requestId} />;
  const property = await loadOrNotFound<PropertyOut>(
    getGetPropertyQueryOptions(meter.data.property_id, { request: { server } }),
    path,
    query,
  );
  if (property.status === "unavailable") return <UnavailablePage requestId={property.requestId} />;

  return (
    <AppPage
      breadcrumb={[
        { label: en.home.breadcrumb, href: "/" },
        { label: property.data.nickname, href: `/properties/${meter.data.property_id}` },
        { label: meter.data.label, href: `/meters/${meterId}` },
        { label: en.invoiceScreens.breadcrumbInvoices },
      ]}
      title={en.invoiceScreens.listTitle}
    >
      <InvoiceListScreen meterId={meterId} zone={property.data.timezone} />
    </AppPage>
  );
}
