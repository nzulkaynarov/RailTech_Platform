import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./errors";
import { FileNotReadyError, downloadFile, filenameFrom } from "./download";

describe("filenameFrom", () => {
  it("обычное имя и запись RFC 5987 (так отдаёт EDS)", () => {
    expect(filenameFrom('attachment; filename="leads-20261026-1430.csv"', "x.csv")).toBe(
      "leads-20261026-1430.csv",
    );
    expect(filenameFrom("attachment; filename*=UTF-8''%D1%81%D1%87%D1%91%D1%82.pdf", "x.pdf")).toBe(
      "счёт.pdf",
    );
    expect(
      filenameFrom(
        `attachment; filename="schet.pdf"; filename*=UTF-8''%D1%81%D1%87%D1%91%D1%82.pdf`,
        "x",
      ),
    ).toBe("счёт.pdf");
  });

  it("нет заголовка или битая запись — запасное имя либо обычное", () => {
    expect(filenameFrom(null, "fallback.bin")).toBe("fallback.bin");
    expect(filenameFrom("attachment", "fallback.bin")).toBe("fallback.bin");
    expect(filenameFrom(`attachment; filename*=UTF-8''%E0%A4%A; filename="ok.txt"`, "x")).toBe(
      "ok.txt",
    );
  });
});

describe("downloadFile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("202 «файл готовится» — FileNotReadyError с паузой, файл не сохраняется (вызывающий обязан показать ошибку)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response('{"detail":"GENERATING","retry_after":3}', {
            status: 202,
            headers: { "Retry-After": "3" },
          }),
        ),
      ),
    );
    const append = vi.spyOn(document.body, "appendChild");
    const failure = await downloadFile("/api/v1/eds/projects/1/files/contract/2", "x.pdf").catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(FileNotReadyError);
    expect((failure as FileNotReadyError).retryAfter).toBe(3);
    expect(failure).not.toBeInstanceOf(ApiError);
    expect(append).not.toHaveBeenCalled();
  });

  it("202 без Retry-After — две секунды; ошибка BFF — ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("{}", { status: 202 }))),
    );
    const failure = await downloadFile("/x", "x.pdf").catch((error: unknown) => error);
    expect((failure as FileNotReadyError).retryAfter).toBe(2);
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response('{"code":"NOT_FOUND","message":"нет","source":"erp"}', { status: 404 }),
        ),
      ),
    );
    await expect(downloadFile("/x", "x.pdf")).rejects.toBeInstanceOf(ApiError);
  });
});
