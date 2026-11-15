import { HttpResponse, http } from "msw";

import type { DictionaryItem } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/** Банки (план 2.9) на моках: вымышленные банки с МФО — подстановка в диалоге банковского счёта компании. */
const BANKS: DictionaryItem[] = [
  {
    code: "00014",
    name: { ru: "АКБ «Демо Банк»", uz: "«Demo Bank» ATB", en: "Demo Bank JSCB" },
    attrs: { swift: "DEMOUZ22" },
    active: true,
    position: 1,
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
    return HttpResponse.json({ items: BANKS });
  }),
];
