/**
 * `pnpm test:e2e` (spec 0011 child 0003 AC-1): the database reset, a production
 * build, then Playwright. The build is a chained step, not a `webServer`
 * command, so build time can't hit Playwright's startup timeout.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { BUILD_ENV } from "../e2e/constants.mjs";

const FRONTEND = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const REPO = path.dirname(FRONTEND);
const RESET = "backend/scripts/reset_e2e_db.py";

function run(command, args, options = {}) {
  // `shell` only so Windows finds the `.cmd` shims; every argument is a constant
  // or comes from this repository.
  const result = spawnSync(command, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    ...options,
    env: { ...process.env, ...options.env },
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
  return result;
}

run("uv", ["run", "python", RESET, "--database", "energyiq_e2e"], { cwd: REPO });
run("pnpm", ["exec", "next", "build"], { cwd: FRONTEND, env: BUILD_ENV });
run("pnpm", ["exec", "playwright", "test", ...process.argv.slice(2)], { cwd: FRONTEND });
