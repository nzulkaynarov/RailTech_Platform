import { afterEach, describe, expect, it, vi } from "vitest";

import i18n from "../i18n";
import { http } from "./http";

describe("http: язык запроса", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    void i18n.changeLanguage("ru");
  });

  it("Accept-Language — язык интерфейса: BFF собирает строки «Главной» на нём (СЦ-7, N1)", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await i18n.changeLanguage("uz");
    await http("/api/v1/queue", { method: "GET" });
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(new Headers(init.headers).get("Accept-Language")).toBe("uz");
  });
});
