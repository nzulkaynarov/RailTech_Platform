import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";
import { reasonText, savedDocumentId, serverFields } from "./errors";

const t = i18n.getFixedT("ru");

function error(status: number, code: string, details: Record<string, unknown> = {}): ApiError {
  return new ApiError(status, code, "текст сервера", "eds", details);
}

describe("ошибки документов", () => {
  it("поля сервера: имена верхнего уровня и пути запроса BFF; незнакомые отбрасываются", () => {
    expect(
      serverFields(
        error(422, "VALIDATION_FAILED", { fields: ["amount", "body.due_date", "kind"] }),
      ),
    ).toEqual(["amount", "due_date"]);
    expect(serverFields(error(422, "VALIDATION_FAILED", { fields: ["amount.amount"] }))).toEqual([
      "amount",
    ]);
    expect(serverFields(new Error("x"))).toEqual([]);
    expect(serverFields(error(500, "X"))).toEqual([]);
  });

  it("причина: подкод важнее поля, поле важнее кода; своего текста нет — общий", () => {
    expect(reasonText(t, error(409, "CONFLICT", { reason: "invalid_state" }))).toBe(
      "документ уже отправлен или закрыт, обновите страницу",
    );
    expect(reasonText(t, error(422, "VALIDATION_FAILED", { fields: ["amount"] }))).toBe(
      "Сумма должна быть больше нуля, например 1 500 000",
    );
    expect(reasonText(t, error(503, "BACKEND_UNAVAILABLE"))).toBe(
      "сервис документов не отвечает, повторите чуть позже",
    );
    expect(reasonText(t, error(403, "FORBIDDEN", { reason: "eds_not_granted" }))).toBe(
      "в сервисе документов у вас нет прав",
    );
    expect(reasonText(t, error(418, "TEAPOT"))).toBe("сервер вернул ошибку, повторите");
    expect(reasonText(t, new TypeError("network"))).toBe("сервер вернул ошибку, повторите");
  });

  it("сохранённый черновик называет сервер", () => {
    expect(
      savedDocumentId(error(503, "BACKEND_UNAVAILABLE", { document_id: "d-1", saved: true })),
    ).toBe("d-1");
    expect(savedDocumentId(error(503, "BACKEND_UNAVAILABLE"))).toBeNull();
    expect(savedDocumentId(null)).toBeNull();
  });
});
