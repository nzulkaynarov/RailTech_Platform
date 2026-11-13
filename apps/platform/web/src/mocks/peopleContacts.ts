import { HttpResponse, http } from "msw";

import type { CounterpartyContacts, CounterpartyPerson } from "../shared/api/generated/model";

/** Люди клиентов и партнёров (FR-11): контакты контрагентов демо-мира, как их отдаёт ERP `parties/people/`. */
const PEOPLE: CounterpartyPerson[] = [
  {
    id: "41",
    name: "Демо Клиентов",
    position: "Главный инженер",
    has_email: true,
    has_phone: true,
    is_primary: true,
    company: { id: "7", name: "АО «Демо-Путь»" },
    kind: "client",
  },
  {
    id: "42",
    name: "Демо Партнёров",
    position: "Менеджер по продажам",
    has_email: true,
    has_phone: false,
    is_primary: true,
    company: { id: "9", name: "ООО «Поставщик Север»" },
    kind: "partner",
  },
];

/** Телефон и почта — только по одному человеку («Показать», BFF пишет показ в журнал). */
const CONTACTS: Record<string, CounterpartyContacts> = {
  "41": { id: "41", phone: "+998901110041", email: "client@demo.example" },
  "42": { id: "42", phone: null, email: "partner@demo.example" },
};

export const peopleContactsHandlers = [
  http.get("*/people/contacts", ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind");
    const items = PEOPLE.filter((person) => !kind || person.kind === kind);
    const pageSize = Number(url.searchParams.get("page_size") ?? "100");
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: pageSize });
  }),
  http.post("*/people/contacts/:id/reveal", ({ params }) => {
    const found = CONTACTS[String(params.id)];
    if (!found) {
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Не найдено.", source: "erp" },
        { status: 404 },
      );
    }
    return HttpResponse.json(found);
  }),
];
