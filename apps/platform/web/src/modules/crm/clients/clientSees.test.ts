import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { resources } from "../../../shared/i18n";

interface ClientStatuses {
  statuses: Record<string, { text: Record<"ru" | "uz" | "en", string> }>;
}

const contract = parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../../../packages/contracts/client-statuses.yaml"),
    "utf8",
  ),
) as ClientStatuses;

describe("«Что видит клиент» в карточке клиента — те же слова, что у бота, в кабинете и письмах", () => {
  it.each(["ru", "uz", "en"] as const)(
    "%s: ключи и тексты совпадают с client-statuses.yaml",
    (lng) => {
      const expected = Object.fromEntries(
        Object.entries(contract.statuses).map(([key, value]) => [key, value.text[lng]]),
      );
      expect(resources[lng].clients.clientSees).toEqual(expected);
    },
  );
});
