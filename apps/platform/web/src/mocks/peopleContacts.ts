import { HttpResponse, http } from "msw";

import type {
  CounterpartyContacts,
  CounterpartyPerson,
  EdsAddressee,
} from "../shared/api/generated/model";
import { pickedCompanyById, pickedPeople } from "./counterpartyPick";
import { findUserById } from "./fixtures/users";
import { clientRefOf, photoUrlOf } from "./pictures";

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
  http.get("*/people/contacts", ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind");
    const items = PEOPLE.filter((person) => !kind || person.kind === kind).map((person) => ({
      ...person,
      photo_url: photoUrlOf(person.id),
      company_logo_url: clientRefOf(person.company.name).client_logo_url,
    }));
    const pageSize = Number(url.searchParams.get("page_size") ?? "100");
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: pageSize });
  }),
  // Решение 10.11: контакты коллеги — по нажатию; телефон и почта — из профиля CRM, показ пишется в журнал
  http.post("*/people/staff/:id/reveal", ({ params }) => {
    const user = findUserById(String(params.id));
    if (!user) {
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Не найдено.", source: "crm" },
        { status: 404 },
      );
    }
    return HttpResponse.json({
      id: user.id,
      phone: `+99890${user.id.replace(/\D/g, "").padStart(7, "0").slice(-7)}`,
      email: user.email,
    });
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
