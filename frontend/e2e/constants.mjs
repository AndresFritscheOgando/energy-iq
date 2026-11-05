/**
 * Fixed ports and flags for the end to end suite (spec 0011 child 0003 AC-3).
 * Fixed because the rewrite target is written at build time and the CSRF origin
 * must match. Its own build folder keeps your normal `.next` pointing at your
 * dev API.
 */
export const API_PORT = 8100;
export const APP_PORT = 3100;
export const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
export const APP_ORIGIN = `http://localhost:${APP_PORT}`;

export const BUILD_ENV = {
  ENERGYIQ_API_ORIGIN: API_ORIGIN,
  ENERGYIQ_EDGE_PROXY: "false",
  ENERGYIQ_NEXT_DIST_DIR: ".next-e2e",
};
