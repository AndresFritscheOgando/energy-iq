// @vitest-environment node
/**
 * Proxy, environment, and header rules from `next.config.ts` (spec 0010
 * AC-2, AC-13), plus the source level invariants that keep the backend
 * origin and the session guard where they belong.
 */
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
  PHASE_PRODUCTION_SERVER,
} from "next/constants";
import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "../next.config";

const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "src");

async function sourceFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { recursive: true, withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && /\.(ts|tsx)$/.test(entry.name))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .filter((file) => !file.includes(`${path.sep}generated${path.sep}`));
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("next.config", () => {
  it("lets dev resources load from 127.0.0.1 so the page hydrates there", () => {
    expect(nextConfig(PHASE_DEVELOPMENT_SERVER).allowedDevOrigins).toContain("127.0.0.1");
  });

  it("matches routes case sensitively so /API cannot bypass proxy.ts (AC-18)", () => {
    expect(nextConfig(PHASE_DEVELOPMENT_SERVER).experimental?.caseSensitiveRoutes).toBe(true);
  });

  it("rewrites /api to the dev default origin outside production", async () => {
    vi.stubEnv("ENERGYIQ_API_ORIGIN", "");
    const config = nextConfig(PHASE_DEVELOPMENT_SERVER);

    expect(await config.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
    ]);
  });

  it("uses ENERGYIQ_API_ORIGIN when set", async () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
    vi.stubEnv("ENERGYIQ_API_ORIGIN", "http://fastapi.internal:9000/");
    const config = nextConfig(PHASE_PRODUCTION_BUILD);

    expect(await config.rewrites?.()).toEqual([
      { source: "/api/:path*", destination: "http://fastapi.internal:9000/api/:path*" },
    ]);
  });

  it.each([PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER])(
    "fails %s without ENERGYIQ_API_ORIGIN, naming the variable",
    async (phase) => {
      vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
      vi.stubEnv("ENERGYIQ_API_ORIGIN", "");
      const config = nextConfig(phase);

      await expect(config.rewrites?.()).rejects.toThrow("ENERGYIQ_API_ORIGIN");
    },
  );

  it.each([PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER])(
    "fails %s unless ENERGYIQ_EDGE_PROXY is exactly true or false, naming the variable",
    (phase) => {
      vi.stubEnv("ENERGYIQ_API_ORIGIN", "http://fastapi.internal:9000");
      for (const bad of ["", "TRUE", "1", "yes", " true"]) {
        vi.stubEnv("ENERGYIQ_EDGE_PROXY", bad);
        expect(() => nextConfig(phase), bad).toThrow("ENERGYIQ_EDGE_PROXY");
      }
      vi.stubEnv("ENERGYIQ_EDGE_PROXY", "true");
      expect(() => nextConfig(phase)).not.toThrow();
      vi.stubEnv("ENERGYIQ_EDGE_PROXY", "false");
      expect(() => nextConfig(phase)).not.toThrow();
    },
  );

  it("does not require ENERGYIQ_EDGE_PROXY in development", () => {
    vi.stubEnv("ENERGYIQ_EDGE_PROXY", "");
    expect(() => nextConfig(PHASE_DEVELOPMENT_SERVER)).not.toThrow();
  });

  it("sends the security headers on every path and hides X-Powered-By", async () => {
    const config = nextConfig(PHASE_DEVELOPMENT_SERVER);
    const rules = await config.headers?.();

    expect(config.poweredByHeader).toBe(false);
    expect(rules?.[0]).toEqual({
      source: "/:path*",
      headers: expect.arrayContaining([
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ]),
    });
  });

  it("sends Cache-Control: no-store on pages but not on /_next or /api (AC-13)", async () => {
    const rules = await nextConfig(PHASE_DEVELOPMENT_SERVER).headers?.();
    const rule = rules?.find((candidate) =>
      candidate.headers.some((header) => header.key === "Cache-Control"),
    );

    expect(rule?.headers).toEqual([{ key: "Cache-Control", value: "no-store" }]);
    const matches = (pathname: string) => new RegExp(`^${rule?.source}$`).test(pathname);
    for (const page of ["/", "/login", "/register", "/Login", "/some/deep/page"]) {
      expect(matches(page), page).toBe(true);
    }
    for (const other of ["/_next/static/chunks/a.js", "/_next/image", "/api/v1/auth/me"]) {
      expect(matches(other), other).toBe(false);
    }
  });
});

describe("source invariants", () => {
  it("reads ENERGYIQ_API_ORIGIN only in server.ts and defines no NEXT_PUBLIC_ variable", async () => {
    const readers: string[] = [];
    for (const file of await sourceFiles(SRC)) {
      const text = await readFile(file, "utf8");
      expect(text, file).not.toContain("NEXT_PUBLIC_");
      if (text.includes("ENERGYIQ_API_ORIGIN")) {
        readers.push(path.relative(ROOT, file).replaceAll("\\", "/"));
      }
    }
    expect(readers).toEqual(["src/lib/api/server.ts"]);
  });

  it("calls fetch only in the mutator", async () => {
    const callers: string[] = [];
    for (const file of await sourceFiles(SRC)) {
      if (/\bfetch\(/.test(await readFile(file, "utf8"))) {
        callers.push(path.relative(ROOT, file).replaceAll("\\", "/"));
      }
    }
    expect(callers).toEqual(["src/lib/api/fetcher.ts"]);
  });

  it("starts every (app) page with requireSession", async () => {
    const appDir = path.join(SRC, "app", "(app)");
    const pages = (await sourceFiles(appDir)).filter((file) => /page\.tsx$/.test(file));

    expect(pages.length).toBeGreaterThan(0);
    for (const page of pages) {
      expect(await readFile(page, "utf8"), page).toMatch(/await requireSession\(/);
    }
  });
});

describe("built client bundle", () => {
  it("never contains the backend origin", async (context) => {
    const staticDir = path.join(ROOT, ".next", "static");
    const exists = await stat(staticDir).then(
      () => true,
      () => false,
    );
    if (!exists) {
      context.skip("no production build in .next; run pnpm build first");
    }
    const entries = await readdir(staticDir, { recursive: true, withFileTypes: true });
    const offenders: string[] = [];
    for (const entry of entries) {
      if (!entry.isFile() || !/\.(js|css|html|json|txt)$/.test(entry.name)) {
        continue;
      }
      const file = path.join(entry.parentPath, entry.name);
      if ((await readFile(file, "utf8")).includes("127.0.0.1:8000")) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});
