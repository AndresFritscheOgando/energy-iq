/**
 * Spec 0010 AC-15. jsdom cannot compute colour contrast, so this guards the
 * cause found in a real browser: `text-destructive/90` blended the red into
 * white and gave 4.49:1 (axe needs 4.5:1). The full colour gives 4.77:1.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("destructive alert", () => {
  it("keeps its text at full destructive strength", () => {
    const source = readFileSync(path.join(__dirname, "../../src/components/ui/alert.tsx"), "utf8");
    expect(source).toContain("*:data-[slot=alert-description]:text-destructive ");
    expect(source).not.toMatch(/text-destructive\/\d+/);
  });
});
