import { HttpResponse, http } from "msw";

import type {
  CounterpartyPersonPick,
  CounterpartyPick,
  CounterpartyPickIn,
} from "../shared/api/generated/model";

/**
 * Поле выбора компании и человека (ЕД-6) на моках: ERP `parties/organizations/` и `parties/people/`. Поиск по названию
 * и ИНН, точный ИНН первым, роль формы поднимает свои строки; дубль ИНН при создании — 409 с id найденной компании.
 */
const roles = (on: Partial<CounterpartyPick["roles"]>): CounterpartyPick["roles"] => ({
  client: false,
  supplier: false,
  manufacturer: false,
  partner: false,
  organization: false,
  ...on,
});

const COMPANIES: CounterpartyPick[] = [
  {
    id: "7",
    name: "АО «Демо-Путь»",
    inn: "300000777",
    country: "Узбекистан",
    roles: roles({ client: true }),
    crm_client_id: 41,
    email: "office@demo-put.example",
  },
  {
    id: "9",
    name: "ООО «Поставщик Север»",
    inn: null,
    country: "Узбекистан",
    roles: roles({ supplier: true, partner: true }),
    crm_client_id: null,
    email: null,
  },
  {
    id: "12",
    name: "ГНИ Мирабадского района",
    inn: "200145778",
    country: "Узбекистан",
    roles: roles({ organization: true }),
    crm_client_id: null,
    email: null,
  },
  {
    id: "13",
    name: "Lokotrans GmbH",
    inn: null,
    country: "Германия",
    roles: roles({ manufacturer: true }),
    crm_client_id: null,
    email: "sales@lokotrans.example",
  },
];

const PEOPLE: Record<string, CounterpartyPersonPick[]> = {
  "7": [
    {
      id: "41",
      name: "Демо Клиентов",
      position: "Главный инженер",
      email: "d.klientov@demo-put.example",
      is_primary: true,
    },
    {
      id: "43",
      name: "Каримова Дилноза",
      position: "Снабжение",
      email: null,
      is_primary: false,
    },
  ],
  "12": [
    {
      id: "51",
      name: "Абдуллаев Б. Т.",
      position: "Начальник отдела",
      email: "abdullaev@gni.example",
      is_primary: true,
    },
  ],
};

export const counterpartyPickHandlers = [
  http.get("*/people/counterparties", ({ request }) => {
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim().toLocaleLowerCase("ru");
    const role = url.searchParams.get("role") as keyof CounterpartyPick["roles"] | null;
    const limit = Number(url.searchParams.get("limit") ?? "10");
    const found = COMPANIES.filter(
      (row) => row.name.toLocaleLowerCase("ru").includes(q) || (row.inn ?? "").includes(q),
    );
    const rank = (row: CounterpartyPick) =>
      (q !== "" && row.inn === q ? 0 : 2) + (role && row.roles[role] ? 0 : 1);
    const items = [...found].sort((a, b) => rank(a) - rank(b)).slice(0, limit);
    return HttpResponse.json({ items });
  }),
  http.post("*/people/counterparties", async ({ request }) => {
    const body = (await request.json()) as CounterpartyPickIn;
    const twin = body.inn ? COMPANIES.find((row) => row.inn === body.inn) : undefined;
    if (twin) {
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Такая компания уже есть.",
          source: "erp",
          details: { reason: "company_exists", existing_id: twin.id },
        },
        { status: 409 },
      );
    }
    const created: CounterpartyPick = {
      id: String(9000 + COMPANIES.length),
      name: body.name.trim(),
      inn: body.inn ?? null,
      country: body.country_id ? "Узбекистан" : null,
      roles: roles({ [body.role ?? "organization"]: true }),
      crm_client_id: null,
      email: null,
    };
    COMPANIES.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),
  http.get("*/people/counterparties/:id/people", ({ params }) => {
    const id = String(params["id"]);
    if (!COMPANIES.some((row) => row.id === id)) {
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Не найдено.", source: "erp" },
        { status: 404 },
      );
    }
    return HttpResponse.json({ items: PEOPLE[id] ?? [] });
  }),
];

/** Компания поля выбора по id — документы и письма на моках берут из неё название и ИНН */
export function pickedCompanyById(id: string): CounterpartyPick | undefined {
  return COMPANIES.find((row) => row.id === id);
}

/** Люди компании поля выбора */
export function pickedPeople(id: string): CounterpartyPersonPick[] {
  return PEOPLE[id] ?? [];
}
