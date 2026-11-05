/**
 * Spec 0010 AC-18 live check (the tripwire for Next.js behavior changes).
 *
 * Puts an echo server where FastAPI would be, builds once, then runs
 * `next start` with ENERGYIQ_EDGE_PROXY=false and =true WITHOUT rebuilding,
 * and shows which X-Forwarded-For the echo server receives:
 *
 *   false: a plain request and one with a spoofed header both arrive with none.
 *   true:  a spoofed header arrives as sent; a plain request arrives with the
 *          socket address (Next.js fills it when the browser sent none).
 *
 * Usage (from frontend/): node scripts/check-edge-proxy.mjs
 * Optional: SKIP_BUILD=1 reuses an existing build made with the same origin.
 */
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";

const ECHO_PORT = 18765;
const NEXT_PORT = 13999;
const ORIGIN = `http://127.0.0.1:${ECHO_PORT}`;
const isWindows = process.platform === "win32";

const received = [];
const echo = createServer((req, res) => {
  received.push(req.headers["x-forwarded-for"] ?? null);
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify({ xForwardedFor: req.headers["x-forwarded-for"] ?? null }));
});
await new Promise((resolve) => echo.listen(ECHO_PORT, "127.0.0.1", resolve));

const baseEnv = { ...process.env, ENERGYIQ_API_ORIGIN: ORIGIN, NODE_ENV: "production" };
let failures = 0;
const check = (label, ok, detail) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}  (${detail})`);
  if (!ok) failures += 1;
};

function pnpm(args, env) {
  return spawn("pnpm", args, { env, shell: isWindows, stdio: ["ignore", "pipe", "pipe"] });
}

try {
  if (!process.env.SKIP_BUILD) {
    const build = spawnSync("pnpm", ["build"], {
      env: { ...baseEnv, ENERGYIQ_EDGE_PROXY: "false" },
      shell: isWindows,
      stdio: "inherit",
    });
    if (build.status !== 0) throw new Error("pnpm build failed");
  }

  // Unset must refuse to start, naming the variable.
  const unsetEnv = { ...baseEnv };
  delete unsetEnv.ENERGYIQ_EDGE_PROXY;
  const unset = spawnSync("pnpm", ["start", "--port", String(NEXT_PORT)], {
    env: unsetEnv,
    shell: isWindows,
    encoding: "utf8",
    timeout: 60_000,
  });
  check(
    "next start with ENERGYIQ_EDGE_PROXY unset fails naming it",
    unset.status !== 0 && `${unset.stdout}${unset.stderr}`.includes("ENERGYIQ_EDGE_PROXY"),
    `exit ${unset.status}`,
  );

  for (const mode of ["false", "true"]) {
    const server = pnpm(["start", "--port", String(NEXT_PORT)], {
      ...baseEnv,
      ENERGYIQ_EDGE_PROXY: mode,
    });
    try {
      const url = `http://127.0.0.1:${NEXT_PORT}/api/v1/auth/me`;
      for (let i = 0; i < 60; i += 1) {
        const up = await fetch(url).then(
          () => true,
          () => false,
        );
        if (up) break;
        await new Promise((r) => setTimeout(r, 500));
      }

      received.length = 0;
      await fetch(url);
      await fetch(url, { headers: { "x-forwarded-for": "6.6.6.6" } });
      const [plain, spoofed] = received.slice(-2);

      if (mode === "false") {
        check("false: plain request arrives with no header", plain === null, String(plain));
        check("false: spoofed 6.6.6.6 is dropped", spoofed === null, String(spoofed));
      } else {
        check(
          "true: plain request arrives with the socket address",
          typeof plain === "string" && plain.length > 0 && !plain.includes("6.6.6.6"),
          String(plain),
        );
        check("true: spoofed 6.6.6.6 arrives as sent", spoofed === "6.6.6.6", String(spoofed));
      }
    } finally {
      if (isWindows) {
        spawnSync("taskkill", ["/pid", String(server.pid), "/t", "/f"]);
      } else {
        server.kill("SIGTERM");
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
} finally {
  echo.close();
}

console.log(failures === 0 ? "\nAll AC-18 live checks passed." : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
