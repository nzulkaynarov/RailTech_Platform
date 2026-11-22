import { describe, expect, it } from "vitest";

import { LetterStatus } from "../../../shared/api/generated/model";
import { statusEntry } from "./statusEntry";

describe("statusEntry", () => {
  it("у каждого статуса входящего письма есть слово: в реестре нет кода вместо статуса (ДОК-8)", () => {
    for (const status of Object.values(LetterStatus)) {
      expect(statusEntry("letter_in", status).key, status).toBe(
        `dictionary:status.incoming.${status}`,
      );
    }
  });

  it("исходящее письмо: «На подписи» только при передаче; статус `draft` без признака — «Черновик» (СЦ-8)", () => {
    expect(statusEntry("letter_out", "draft", true)).toEqual({
      kind: "memo",
      key: "documents:status.signing",
      code: "signing",
    });
    expect(statusEntry("letter_out", "draft", false).key).toBe("documents:status.draft");
    expect(statusEntry("letter_out", "draft").key).toBe("documents:status.draft");
    // после подписи признак гаснет, и слово — «Зарегистрировано»
    expect(statusEntry("letter_out", "sent", false).key).toBe("documents:status.sent");
    // признак не меняет слово чужих видов
    expect(statusEntry("memo", "draft", true).key).toBe("documents:status.draft");
  });
});
