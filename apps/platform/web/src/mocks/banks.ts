import { HttpResponse, http } from "msw";

import type { DictionaryItem } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

const CBU = { ru: "ЦБ", uz: "MB", en: "CBU" };
const monthStart = (monthsBack: number) => {
  const at = new Date();
  at.setDate(1);
  at.setMonth(at.getMonth() - monthsBack);
  at.setHours(3, 30, 0, 0);
  return at.toISOString();
};

/**
 * Банки (план 2.9, Х-12) на моках: вымышленные банки с МФО — подстановка в диалоге банковского счёта компании.
 * Источник — файл ЦБ раз в месяц: у одной строки код пропал из последнего файла (не удалён, дата — прошлого файла),
 * одна добавлена вручную.
 */
const banks = (): DictionaryItem[] => [
  {
    code: "00014",
    name: { ru: "АКБ «Демо Банк»", uz: "«Demo Bank» ATB", en: "Demo Bank JSCB" },
    attrs: { swift: "DEMOUZ22" },
    active: true,
    position: 1,
    source: { name: CBU, synced_at: monthStart(0), missing: false },
  },
  {
    code: "00441",
    name: {
      ru: "ЧАКБ «Вымышленный Капитал»",
      uz: "«Vymyshlenny Kapital» XATB",
      en: "Fictional Capital PJSCB",
    },
    attrs: { swift: "FICTUZ2X" },
    active: true,
    position: 2,
    source: { name: CBU, synced_at: monthStart(0), missing: false },
  },
  {
    code: "00401",
    name: { ru: "АКБ «Старый Банк»", uz: "«Eski Bank» ATB", en: "Old Bank JSCB" },
    attrs: { swift: "" },
    active: true,
    position: 3,
    source: { name: CBU, synced_at: monthStart(1), missing: true },
  },
  {
    code: "99001",
    name: {
      ru: "Банк, добавленный вручную",
      uz: "Qölda qöşilgan bank",
      en: "Manually added bank",
    },
    attrs: { swift: "" },
    active: true,
    position: 4,
    source: null,
  },
];

export const banksHandlers = [
  http.get("*/dictionaries/banks", () => {
    if (!readSession()) {
      return HttpResponse.json(
        { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
        { status: 401 },
      );
    }
    return HttpResponse.json({ items: banks() });
  }),
];
