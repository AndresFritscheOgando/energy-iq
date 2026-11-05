import { setupServer } from "msw/node";

/** One MSW server for every test; each test adds its own handlers. */
export const server = setupServer();
