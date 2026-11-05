import { defineConfig } from "orval";

/**
 * Spec 0010 AC-3: the typed client is generated from the committed backend
 * OpenAPI snapshot. The output is committed; `tests/api/codegen.test.ts`
 * regenerates it into a temporary folder and fails on any difference.
 */
export const OPENAPI_SNAPSHOT = "../backend/tests/snapshots/openapi.json";
export const GENERATED_DIR = "src/lib/api/generated";

export function energyiqOutput(dir: string) {
  return {
    mode: "tags-split" as const,
    target: `${dir}/energyiq.ts`,
    schemas: `${dir}/model`,
    client: "react-query" as const,
    httpClient: "fetch" as const,
    clean: true,
    override: {
      mutator: {
        path: "src/lib/api/fetcher.ts",
        name: "apiFetch",
      },
      fetch: {
        includeHttpResponseReturnType: false,
      },
    },
  };
}

export default defineConfig({
  energyiq: {
    input: { target: OPENAPI_SNAPSHOT },
    output: energyiqOutput(GENERATED_DIR),
  },
});
