import { HttpResponse, sse } from "msw";

import type { InvalidationHint } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/**
 * Поток подсказок BFF (`GET /api/v1/events/stream`) для `pnpm dev:mock` и e2e: соединение открыто и молчит, пока сценарий
 * не пошлёт подсказку `window.__rtMockEmitHint({ topics, reason })` (ставится в `mocks/browser.ts`). Так e2e проверяет
 * путь «подсказка → перезапрос → обновлённый экран» без BFF и шины.
 */
type MockClient = { send(payload: { event: "invalidate"; data: string }): void; close(): void };
const clients = new Set<MockClient>();

export function emitMockHint(hint: InvalidationHint): void {
  for (const client of clients) client.send({ event: "invalidate", data: JSON.stringify(hint) });
}

export function mockStreamCount(): number {
  return clients.size;
}

/** Оборвать все потоки (для сценария «поток упал, опрос продолжает»). */
export function dropMockStreams(): void {
  for (const client of clients) client.close();
  clients.clear();
}

/** `sse()` требует `EventSource` в окружении: в браузере он есть, в jsdom (vitest) нет — там поток подменяет `FakeEventSource`. */
export const eventStreamHandlers =
  typeof EventSource === "undefined"
    ? []
    : [
        sse<{ invalidate: string }>("*/api/v1/events/stream", ({ client }) => {
          if (!readSession()) {
            return HttpResponse.json(
              { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
              { status: 401 },
            );
          }
          clients.add(client);
          return undefined;
        }),
      ];
