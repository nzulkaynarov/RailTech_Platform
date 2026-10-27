import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { ApiError } from "./errors";
import { http as request } from "./http";
import { withTimeout } from "./timeout";

describe("предел ожидания", () => {
  it("зависший ответ даёт ApiError REQUEST_TIMEOUT, а не вечную загрузку", async () => {
    server.use(
      http.get("*/slow-setup", async () => {
        await delay(400);
        return HttpResponse.json({});
      }),
    );

    const error = await request("/api/v1/slow-setup", { signal: withTimeout(undefined, 30) }).catch(
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("REQUEST_TIMEOUT");
  });

  it("отмена запроса react-query остаётся отменой, а не таймаутом", async () => {
    server.use(
      http.get("*/slow-setup", async () => {
        await delay(400);
        return HttpResponse.json({});
      }),
    );
    const controller = new AbortController();

    const pending = request("/api/v1/slow-setup", {
      signal: withTimeout(controller.signal, 5_000),
    }).catch((e: unknown) => e);
    controller.abort();

    const error = await pending;
    expect(error).not.toBeInstanceOf(ApiError);
  });
});
