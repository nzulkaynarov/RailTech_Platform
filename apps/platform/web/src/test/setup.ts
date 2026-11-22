import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, expect } from "vitest";

import i18n from "../shared/i18n";
import { humanTextProblems, missingKeys, recordMissingKey, visibleText } from "./humanText";
import { ALLOWED_HUMAN_TEXT, ALLOWED_MISSING_KEYS } from "./humanTextAllowList";
import { server } from "./server";

configure({ asyncUtilTimeout: 5_000 });

// jsdom не реализует matchMedia/ResizeObserver, а Ant Design их использует.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

if (!("ResizeObserver" in window)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.defineProperty(window, "ResizeObserver", { writable: true, value: ResizeObserverStub });
}

// Node fetch не разрешает относительные адреса (`/api/v1/...`) — в браузере это делает страница.
const nativeFetch = globalThis.fetch.bind(globalThis);

/**
 * `FormData` и `File` в jsdom — не те, что понимает Node fetch (тело уходит как «[object FormData]» или обрывается):
 * форму загрузки файла собираем в multipart вручную, как это делает браузер.
 */
async function multipartInit(form: FormData, init: RequestInit): Promise<RequestInit> {
  const boundary = `----pfTest${Math.random().toString(16).slice(2)}`;
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  for (const [name, value] of form.entries()) {
    if (typeof value === "string") {
      parts.push(
        encoder.encode(
          `--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`,
        ),
      );
    } else {
      parts.push(
        encoder.encode(
          `--${boundary}\r\nContent-Disposition: form-data; name="${name}"; filename="${value.name}"\r\n` +
            `Content-Type: ${value.type || "application/octet-stream"}\r\n\r\n`,
        ),
        new Uint8Array(await value.arrayBuffer()),
        encoder.encode("\r\n"),
      );
    }
  }
  parts.push(encoder.encode(`--${boundary}--\r\n`));
  const body = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    body.set(part, offset);
    offset += part.length;
  }
  const headers = new Headers(init.headers);
  headers.set("Content-Type", `multipart/form-data; boundary=${boundary}`);
  return { ...init, headers, body };
}

globalThis.fetch = (input, init) =>
  nativeFetch(
    typeof input === "string" && input.startsWith("/")
      ? new URL(input, window.location.origin)
      : input,
    init,
  );

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  // MSW подменяет fetch при `listen`: форму файла переводим в multipart уже поверх него, до разбора запроса.
  const intercepted = globalThis.fetch;
  globalThis.fetch = async (input, init) =>
    intercepted(
      input,
      init?.body instanceof FormData ? await multipartInit(init.body, init) : init,
    );
});
afterEach(() => {
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});

// jsdom не умеет прокручивать: Настройки (SET-IA) прокручивают к группе и к части страницы по адресу.
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => undefined;
}

// Охранник «человеческого текста» (СЦ-7, `humanText.ts`): ключ без перевода и без `defaultValue` попадает в `missingKeys`,
// а после теста текст экрана сканируется на сырые ключи и коды событий, даты ISO, суммы без разрядов, «(и)»/«(а)» и «#2».
// Выключить на один тест нельзя; известные чужие нарушения — в `humanTextAllowList.ts`.
i18n.options.saveMissing = true;
i18n.options.missingKeyHandler = (_languages, namespace, key, _fallback, _update, options) => {
  recordMissingKey(namespace, key, options as { defaultValue?: unknown } | undefined);
};

// Хук объявлен после импорта RTL: он выполняется раньше его очистки (хуки afterEach идут в обратном порядке),
// поэтому `document.body` ещё содержит экран теста.
afterEach(() => {
  const file = expect.getState().testPath ?? "";
  const problems = humanTextProblems(
    file,
    visibleText(document.body),
    missingKeys,
    ALLOWED_HUMAN_TEXT,
    ALLOWED_MISSING_KEYS,
  );
  missingKeys.clear();
  if (problems.length > 0) {
    throw new Error(`Человек такое не читает (СЦ-7):\n${problems.map((p) => `  ${p}`).join("\n")}`);
  }
});
