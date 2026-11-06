import { AppPage, UnavailablePage } from "@/components/app/AppPage";
import { InvoiceReview } from "@/components/invoices/InvoiceReview";
import { getGetInvoiceQueryOptions } from "@/lib/api/generated/invoices/invoices";
import { getGetMeterQueryOptions } from "@/lib/api/generated/meters/meters";
import type { InvoiceOut, MeterOut, PropertyOut } from "@/lib/api/generated/model";
import { getGetPropertyQueryOptions } from "@/lib/api/generated/properties/properties";
import { loadOrNotFound, requireSession, serverRequestInit } from "@/lib/api/server";
import { en } from "@/messages/en";

export default async function InvoicePage({
  params,
  searchParams,
}: PageProps<"/invoices/[invoiceId]">) {
  const { invoiceId } = await params;
  const query = await searchParams;
  const path = `/invoices/${invoiceId}`;
  const session = await requireSession(path, query);
  if (session.status === "unavailable") return <UnavailablePage requestId={session.requestId} />;

  const server = await serverRequestInit();
  const invoice = await loadOrNotFound<InvoiceOut>(
    getGetInvoiceQueryOptions(invoiceId, { request: { server } }),
    path,
    query,
  );
  if (invoice.status === "unavailable") return <UnavailablePage requestId={invoice.requestId} />;
  const meterId = invoice.data.meter_id;
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
        { label: en.invoiceScreens.breadcrumbInvoices, href: `/meters/${meterId}/invoices` },
        { label: en.invoiceScreens.reviewTitle },
      ]}
      title={en.invoiceScreens.reviewTitle}
    >
      <InvoiceReview invoiceId={invoiceId} zone={property.data.timezone} />
    </AppPage>
  );
}
