/**
 * Chrome only. This layout is NOT the session guard: a layout cannot see the
 * URL and is not rerendered when the user moves between pages under it, so
 * every `(app)` page calls `requireSession` itself (spec 0010 AC-6). The header
 * lives in `AppPage`, because it needs the page's hydrated `/auth/me`.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-1 flex-col">{children}</div>;
}
