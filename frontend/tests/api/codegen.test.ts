// @vitest-environment node
/**
 * The committed Orval output matches the backend snapshot (spec 0010 AC-3).
 *
 * Orval regenerates into a sibling folder at the same depth as the real
 * output, so relative imports of the mutator are identical, and every file
 * must match byte for byte. Run `pnpm gen:api` after an API change.
 */
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";

import { generate } from "orval";
import { afterAll, describe, expect, it } from "vitest";

import { energyiqOutput, GENERATED_DIR, OPENAPI_SNAPSHOT } from "../../orval.config";

const ROOT = path.resolve(__dirname, "../..");
const COMMITTED = path.join(ROOT, GENERATED_DIR);

async function listFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { recursive: true, withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) =>
      path.relative(dir, path.join(entry.parentPath, entry.name)).replaceAll("\\", "/"),
    )
    .sort();
}

let scratch: string | undefined;

afterAll(async () => {
  if (scratch) {
    await rm(scratch, { recursive: true, force: true });
  }
});

describe("generated API client", () => {
  it("is exactly what Orval produces from the committed snapshot", async () => {
    scratch = await mkdtemp(path.join(path.dirname(COMMITTED), ".drift-"));
    const relative = path.relative(ROOT, scratch).replaceAll("\\", "/");

    await generate({ input: { target: OPENAPI_SNAPSHOT }, output: energyiqOutput(relative) }, ROOT);

    const expected = await listFiles(scratch);
    expect(await listFiles(COMMITTED)).toEqual(expected);
    for (const file of expected) {
      const fresh = await readFile(path.join(scratch, file), "utf8");
      const committed = await readFile(path.join(COMMITTED, file), "utf8");
      expect(committed, `${file} is stale: run pnpm gen:api`).toBe(fresh);
    }
  });

  it("keeps both health routes in the health tag file", async () => {
    const health = await readFile(path.join(COMMITTED, "health/health.ts"), "utf8");

    expect(health).toContain("`/health`");
    expect(health).toContain("`/health/ready`");
  });

  it("keeps decimal fields as strings and never converts them to numbers", async () => {
    const summary = await readFile(
      path.join(COMMITTED, "model/consumptionSummaryResponse.ts"),
      "utf8",
    );
    const files = await listFiles(COMMITTED);
    const all = await Promise.all(
      files.map((file) => readFile(path.join(COMMITTED, file), "utf8")),
    );

    expect(summary).toMatch(/measured_kwh: string;/);
    for (const text of all) {
      expect(text).not.toMatch(/\bparseFloat\(|\bNumber\(/);
    }
  });
});
