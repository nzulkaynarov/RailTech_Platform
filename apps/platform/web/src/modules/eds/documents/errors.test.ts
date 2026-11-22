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
    expect(
      serverFields(error(422, "VALIDATION_FAILED", { fields: ["body.letter.signer_crm_user_id"] })),
    ).toEqual(["signer_crm_user_id"]);
    expect(serverFields(new Error("x"))).toEqual([]);
    expect(serverFields(error(500, "X"))).toEqual([]);
  });

  it("отказ подписи: настоящая причина EDS, а не «не положено вашей роли»", () => {
    for (const reason of [
      "no_authority",
      "author_cannot_sign",
      "authority_mismatch",
      "revoked",
      "not_started",
      "expired",
      "limit_exceeded",
      "currency_mismatch",
      "holder_inactive",
      "absent",
      "deputy_without_authority",
      "deputy_loop",
      "no_permission",
      "no_signing_authority",
    ]) {
      const text = reasonText(t, error(403, "FORBIDDEN", { reason }));
      expect(text, reason).not.toBe("действие не положено вашей роли");
      expect(text, reason).not.toBe(reasonText(t, error(500, "X")));
    }
    expect(reasonText(t, error(403, "FORBIDDEN", { reason: "no_authority" }))).toBe(
      "полномочие подписи никому не выдано",
    );
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
