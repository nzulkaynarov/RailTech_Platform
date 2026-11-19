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
});
