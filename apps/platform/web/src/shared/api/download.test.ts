import { describe, expect, it } from "vitest";

import { filenameFrom } from "./download";

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
