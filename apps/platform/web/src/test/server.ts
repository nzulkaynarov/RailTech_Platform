import { setupServer } from "msw/node";

import { handlers } from "../mocks/handlers";

/** Сервер MSW для vitest: те же моки orval, что в `dev:mock`; тесты переопределяют через `server.use`. */
export const server = setupServer(...handlers);
