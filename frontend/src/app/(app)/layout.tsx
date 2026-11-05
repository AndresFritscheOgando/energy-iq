import { en } from "@/messages/en";

/**
 * Chrome only. This layout is NOT the session guard: a layout cannot see the
 * URL and is not rerendered when the user moves between pages under it, so
 * every `(app)` page calls `requireSession` itself (spec 0010 AC-6).
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b px-6 py-4">
        <p className="font-heading text-lg font-semibold">{en.appName}</p>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
