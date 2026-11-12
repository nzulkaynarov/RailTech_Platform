import { HttpResponse, http } from "msw";

import type { CounterpartyPerson } from "../shared/api/generated/model";

/** Люди клиентов и партнёров (FR-11): контакты контрагентов демо-мира, как их отдаёт ERP `parties/people/`. */
const PEOPLE: CounterpartyPerson[] = [
  {
    id: "41",
    name: "Демо Клиентов",
    position: "Главный инженер",
    email: "client@demo.example",
    phone: "+998901110041",
    is_primary: true,
    company: { id: "7", name: "АО «Демо-Путь»" },
    kind: "client",
  },
  {
    id: "42",
    name: "Демо Партнёров",
    position: "Менеджер по продажам",
    email: "partner@demo.example",
    phone: null,
    is_primary: true,
    company: { id: "9", name: "ООО «Поставщик Север»" },
    kind: "partner",
  },
];

export const peopleContactsHandlers = [
  http.get("*/people/contacts", ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind");
    const items = PEOPLE.filter((person) => !kind || person.kind === kind);
    const pageSize = Number(url.searchParams.get("page_size") ?? "100");
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: pageSize });
  }),
];
