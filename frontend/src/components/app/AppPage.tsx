/**
 * The frame of every signed in page (spec 0011): product name, account
 * controls, breadcrumb, and title, inside the page's hydrated query state.
 * A server component; the `(app)` layout stays free of data on purpose.
 */
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { ApiUnavailable } from "@/components/ApiUnavailable";
import { getServerQueryClient } from "@/lib/api/server";
import { en } from "@/messages/en";

import { AccountControls } from "./AccountControls";

export type Crumb = { label: string; href?: string };

type Props = {
  breadcrumb: readonly Crumb[];
  title: string;
  /** Beside the title: a marker or a quiet subtitle. */
  titleAside?: ReactNode;
  children: ReactNode;
};

export function AppHeader({ account }: { account: boolean }) {
  return (
    <header className="border-b">
      <div className="mx-auto flex w-full max-w-[1248px] items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2 font-semibold">
          <span aria-hidden="true" className="size-2.5 rounded-[3px] bg-primary" />
          {en.appName}
        </Link>
        {account && <AccountControls />}
      </div>
    </header>
  );
}

export function AppPage({ breadcrumb, title, titleAside, children }: Props) {
  return (
    <HydrationBoundary state={dehydrate(getServerQueryClient())}>
      <AppHeader account />
      <main className="mx-auto flex w-full max-w-[1248px] flex-1 flex-col gap-6 px-4 py-5 sm:px-6">
        <div className="flex flex-col gap-3">
          <nav aria-label="Breadcrumb">
            <ol className="flex flex-wrap items-center gap-1.5 text-[13px] leading-5">
              {breadcrumb.map((crumb, index) => (
                <li key={crumb.label} className="flex items-center gap-1.5">
                  {index > 0 && (
                    <span aria-hidden="true" className="text-muted-foreground">
                      /
                    </span>
                  )}
                  {crumb.href ? (
                    <Link
                      href={crumb.href}
                      className="text-muted-foreground underline underline-offset-4"
                    >
                      {crumb.label}
                    </Link>
                  ) : (
                    <span aria-current="page">{crumb.label}</span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-2xl leading-8 font-semibold break-words">{title}</h1>
            {titleAside}
          </div>
        </div>
        {children}
      </main>
    </HydrationBoundary>
  );
}

/** The whole page when a server read can't reach the API (spec 0010 AC-12). */
export function UnavailablePage({ requestId }: { requestId: string | null }) {
  return (
    <>
      <AppHeader account={false} />
      <main className="mx-auto w-full max-w-[1248px] flex-1 px-4 py-5 sm:px-6">
        <ApiUnavailable requestId={requestId} />
      </main>
    </>
  );
}
