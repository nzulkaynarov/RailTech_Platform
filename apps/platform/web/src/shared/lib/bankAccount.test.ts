import { describe, expect, it } from "vitest";

import {
  accountProblem,
  countryOf,
  grouped,
  latinProblem,
  mfoProblem,
  swiftProblem,
} from "./bankAccount";

describe("банковский счёт (ADR-0029)", () => {
  it.each([
    ["uz", "2020 8000 9000 0000 0001", "UZS", null],
    ["uz", "2020800090", "UZS", "uz_format"],
    ["uz", "20208840900000000001", "UZS", "currency_mismatch"],
    ["uz", "20208840900000000001", "USD", null],
    ["abroad", "DE89 3704 0044 0532 0130 00", "EUR", null],
    ["abroad", "DE89 3704 0044 0532 0130 01", "EUR", "iban_invalid"],
    ["abroad", "000123456789", "USD", null],
    ["abroad", "12-ab!", "USD", "format"],
    ["abroad", "", "USD", "required"],
  ] as const)("%s %s %s → %s", (place, account, currency, problem) => {
    expect(accountProblem(place, account, currency)).toBe(problem);
  });

  it("МФО, SWIFT, латиница и страна банка", () => {
    expect(mfoProblem("uz", "00440")).toBeNull();
    expect(mfoProblem("uz", "440")).toBe("uz_format");
    expect(mfoProblem("abroad", "")).toBeNull();
    expect(swiftProblem("cobadeff", true)).toBeNull();
    expect(swiftProblem("", true)).toBe("required");
    expect(swiftProblem("NOTABIC", false)).toBe("invalid");
    expect(latinProblem("ООО Пример")).toBe("latin_charset");
    expect(countryOf("abroad", "COBADEFFXXX")).toBe("DE");
    expect(countryOf("uz", "")).toBe("UZ");
    expect(grouped("DE89370400440532013000")).toBe("DE89 3704 0044 0532 0130 00");
  });
});
