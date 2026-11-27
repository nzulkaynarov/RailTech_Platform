import { setupWorker } from "msw/browser";

import type { InvalidationHint } from "../shared/api/generated/model";
import { dropMockStreams, emitMockHint, mockStreamCount } from "./eventStream";
import { pushMockNotification } from "./feedHandlers";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

declare global {
  interface Window {
    /** Только моки: послать открытым потокам подсказку BFF (e2e и ручная проверка в `pnpm dev:mock`). */
    __rtMockEmitHint?: (hint: InvalidationHint) => void;
    /** Только моки: оборвать потоки подсказок. */
    __rtMockDropStreams?: () => void;
    /** Только моки: «пришло» уведомление (e2e УВЕД-1) — добавляет в ленту и шлёт подсказку `notifications`, `counters`. */
    __rtMockPushNotification?: (note: Parameters<typeof pushMockNotification>[0]) => void;
    /** Только моки: сколько потоков подсказок сейчас открыто. */
    __rtMockStreamCount?: () => number;
  }
}
window.__rtMockEmitHint = emitMockHint;
window.__rtMockPushNotification = (note) => {
  pushMockNotification(note);
  emitMockHint({ topics: ["notifications", "counters"], reason: "e2e.notification" });
};
window.__rtMockDropStreams = dropMockStreams;
window.__rtMockStreamCount = mockStreamCount;
