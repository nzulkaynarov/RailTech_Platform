import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

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
