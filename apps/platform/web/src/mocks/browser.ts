import { setupWorker } from "msw/browser";

import type { InvalidationHint } from "../shared/api/generated/model";
import { dropMockStreams, emitMockHint, mockStreamCount } from "./eventStream";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

declare global {
  interface Window {
    /** Только моки: послать открытым потокам подсказку BFF (e2e и ручная проверка в `pnpm dev:mock`). */
    __rtMockEmitHint?: (hint: InvalidationHint) => void;
    /** Только моки: оборвать потоки подсказок. */
    __rtMockDropStreams?: () => void;
    /** Только моки: сколько потоков подсказок сейчас открыто. */
    __rtMockStreamCount?: () => number;
  }
}
window.__rtMockEmitHint = emitMockHint;
window.__rtMockDropStreams = dropMockStreams;
window.__rtMockStreamCount = mockStreamCount;
