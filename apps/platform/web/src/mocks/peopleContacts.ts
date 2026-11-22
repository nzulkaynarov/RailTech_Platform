import { HttpResponse, http } from "msw";

import type {
  CounterpartyContacts,
  CounterpartyPerson,
  EdsAddressee,
  EdsAddresseeIn,
} from "../shared/api/generated/model";
import { pickedCompanyById, pickedPeople } from "./counterpartyPick";

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

/** Организации-контрагенты для «Организации» письма (пункт «Ш»): ERP `parties/organizations/`. */
const ADDRESSEES: EdsAddressee[] = [
  {
    id: "7",
    name: "АО «Демо-Путь»",
    inn: "300000777",
    email: "office@demo-put.example",
    attention: "Демо Клиентов",
    kind: "client",
  },
  {
    id: "9",
    name: "ООО «Поставщик Север»",
    inn: null,
    email: null,
    attention: null,
    kind: "partner",
  },
];

/** Адресат письма по id (СУЩ-2.6): BFF берёт название и ИНН из карточки компании ERP. */
export function addresseeById(id: string): EdsAddressee | undefined {
  const own = ADDRESSEES.find((item) => item.id === id);
  if (own) return own;
  // компании поля выбора (ЕД-6), в том числе заведённые из формы
  const picked = pickedCompanyById(id);
  return picked
    ? {
        id: picked.id,
        name: picked.name,
        inn: picked.inn,
        email: picked.email,
        attention: null,
        kind: "partner",
      }
    : undefined;
}

/** Люди компании-адресата — «Кому — человек». */
export function addresseePeople(
  id: string,
): { id: string; name: string; position: string | null }[] {
  const own = PEOPLE.filter((person) => person.company.id === id);
  return [...own, ...pickedPeople(id).filter((p) => !own.some((o) => o.id === p.id))];
}

export const peopleContactsHandlers = [
  http.get("*/eds/addressees/:id/people", ({ params }) => {
    const id = String(params.id);
    if (!addresseeById(id)) {
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Не найдено.", source: "erp" },
        { status: 404 },
      );
    }
    const items = addresseePeople(id).map(({ id: personId, name, position }) => ({
      id: personId,
      name,
      position,
    }));
    return HttpResponse.json({ items });
  }),
  http.get("*/eds/addressees", ({ request }) => {
    const q = (new URL(request.url).searchParams.get("q") ?? "").toLocaleLowerCase("ru");
    const items = ADDRESSEES.filter(
      (item) => item.name.toLocaleLowerCase("ru").includes(q) || (item.inn ?? "").includes(q),
    );
    return HttpResponse.json({ items });
  }),
  // СУЩ-2.6: организация-адресат из письма; дубль по ИНН или названию — 409, как у ERP
  http.post("*/eds/addressees", async ({ request }) => {
    const body = (await request.json()) as EdsAddresseeIn;
    const name = body.name.trim();
    const taken = ADDRESSEES.some(
      (item) =>
        (body.inn && item.inn === body.inn) ||
        item.name.toLocaleLowerCase("ru") === name.toLocaleLowerCase("ru"),
    );
    if (taken) {
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Такая компания уже есть. Найдите её в списке.",
          source: "erp",
          details: { reason: "company_exists" },
        },
        { status: 409 },
      );
    }
    const created: EdsAddressee = {
      id: String(9000 + ADDRESSEES.length),
      name,
      inn: body.inn ?? null,
      email: null,
      attention: null,
      kind: "partner",
    };
    ADDRESSEES.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),
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
