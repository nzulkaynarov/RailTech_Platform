import { HttpResponse, http } from "msw";

import type { CounterpartyCard, CounterpartyRoleIn } from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { readErpCatalog } from "./fixtures/erpCatalog";
import { readLeads } from "./fixtures/leads";
import { buildMe, readSession } from "./mockSession";

/**
 * Карточка контрагента на моках (ADR-0028, СУЩ-2.5): компания ERP — поставщик каталога (id поставщика) или клиент CRM,
 * переданный в ERP (id = 1000 + id клиента). Роли-отметки хранятся здесь же; номера счетов полностью видит тот, у кого
 * есть раздел оплат.
 */
const CLIENT_BASE = 1000;
const marks = new Map<string, { supplier?: boolean; manufacturer?: boolean }>();

function level(resource: "crm.clients" | "erp.stock" | "eds.payments"): string | undefined {
  const session = readSession();
  return session ? buildMe({ ...session, activeRole: null })?.resources[resource] : undefined;
}

function cardOf(id: string): CounterpartyCard | null {
  const masked = !level("eds.payments");
  const account = masked ? "…0001" : "2020 8000 9000 0000 0001";
  const mark = marks.get(id) ?? {};
  const state = readErpCatalog();
  const supplier = state.suppliers.find((row) => row.id === id);
  if (supplier) {
    const brands = state.manufacturers
      .filter((brand) => brand.company_id === id)
      .map((brand) => ({ id: brand.id, name: brand.name }));
    return {
      id,
      name: supplier.name,
      inn: supplier.tin || null,
      registration_number: supplier.registration_number || null,
      country: supplier.country || null,
      legal_address: supplier.legal_address || null,
      crm_client_id: null,
      roles: {
        client: false,
        supplier: true,
        manufacturer: mark.manufacturer ?? (supplier.is_manufacturer || brands.length > 0),
        partner: false,
      },
      people: supplier.contact_person
        ? [
            {
              id: `9${id}`,
              name: supplier.contact_person,
              position: "Менеджер по продажам",
              is_primary: true,
              has_cabinet: false,
              has_phone: Boolean(supplier.phone),
              has_email: Boolean(supplier.email),
            },
          ]
        : [],
      bank_accounts: [
        {
          id: `7${id}`,
          currency: "UZS",
          bank_name: "АКБ «Демо Банк»",
          bank_country: "UZ",
          account,
          mfo: "00014",
          swift: "",
          is_default: true,
        },
      ],
      accounts_masked: masked,
      brands,
    };
  }
  const client = readLeads().clients.find((row) => String(CLIENT_BASE + row.id) === id);
  if (!client?.in_erp) return null;
  return {
    id,
    name: client.name,
    inn: client.inn ?? null,
    registration_number: null,
    country: "Узбекистан",
    legal_address: null,
    crm_client_id: client.id,
    roles: {
      client: true,
      supplier: mark.supplier ?? false,
      manufacturer: mark.manufacturer ?? false,
      partner: false,
    },
    people: client.contacts.map((contact, index) => ({
      id: String(contact.id),
      name: contact.name,
      position: contact.position ?? null,
      is_primary: index === 0,
      has_cabinet: false,
      has_phone: true,
      has_email: true,
    })),
    bank_accounts: [],
    accounts_masked: masked,
    brands: [],
  };
}

const notFound = () => failure(404, "NOT_FOUND", "Контрагент не найден.", "erp");

function guard(write = false) {
  if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const allowed = write
    ? level("erp.stock") === "full"
    : level("crm.clients") || level("erp.stock");
  return allowed
    ? null
    : failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff");
}

export const counterpartyHandlers = [
  http.get("*/people/clients/:id/counterparty", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    const card = cardOf(String(CLIENT_BASE + Number(params["id"])));
    return card ? HttpResponse.json(card) : notFound();
  }),
  http.get("*/people/counterparties/:id", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    const card = cardOf(String(params["id"]));
    return card ? HttpResponse.json(card) : notFound();
  }),
  http.post("*/people/counterparties/:id/roles", async ({ params, request }) => {
    const denied = guard(true);
    if (denied) return denied;
    const id = String(params["id"]);
    const before = cardOf(id);
    if (!before) return notFound();
    const body = (await request.json()) as CounterpartyRoleIn;
    const state = readErpCatalog();
    const inUse =
      !body.on &&
      (body.role === "supplier"
        ? state.suppliers.some((row) => row.id === id)
        : state.manufacturers.some((brand) => brand.company_id === id));
    if (inUse) {
      return failure(409, "CONFLICT", "Роль занята.", "erp", { reason: "role_in_use" });
    }
    marks.set(id, { ...marks.get(id), [body.role]: body.on });
    return HttpResponse.json(cardOf(id));
  }),
];
