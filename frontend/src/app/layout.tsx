import type { Metadata } from "next";

import { QueryProvider } from "@/components/QueryProvider";
import { en } from "@/messages/en";

import "./globals.css";

export const metadata: Metadata = {
  title: en.appName,
  description: en.metaDescription,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
