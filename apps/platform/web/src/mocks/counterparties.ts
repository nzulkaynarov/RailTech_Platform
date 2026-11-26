import { HttpResponse, http } from "msw";

import type {
  CounterpartyCard,
  CounterpartyRequisitesIn,
  CounterpartyRoleIn,
  DoNotWorkIn,
} from "../shared/api/generated/model";
import { clearMark, markOf, setMark } from "./doNotWorkMarks";
import { failure } from "./adminUsers";
import { readErpCatalog } from "./fixtures/erpCatalog";
import { readLeads } from "./fixtures/leads";
import { buildMe, currentActor, readSession } from "./mockSession";
import { logoUrlOf, photoUrlOf, pictureHandlers } from "./pictures";

/**
 * Карточка контрагента на моках (ADR-0028, СУЩ-2.5): компания ERP — поставщик каталога (id поставщика) или клиент CRM,
 * переданный в ERP (id = 1000 + id клиента). Роли-отметки хранятся здесь же; номера счетов полностью видит тот, у кого
 * есть раздел оплат.
 */
const CLIENT_BASE = 1000;
const marks = new Map<string, { supplier?: boolean; manufacturer?: boolean }>();
/** Реквизиты, поправленные в карточке (СУЩ-2.7): поверх данных каталога и клиентов */
const requisites = new Map<string, Partial<CounterpartyCard>>();

function level(resource: "crm.clients" | "erp.stock" | "eds.payments"): string | undefined {
  const session = readSession();
  return session ? buildMe(session)?.resources[resource] : undefined;
}

function baseCardOf(id: string): CounterpartyCard | null {
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
        organization: false,
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
      organization: false,
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
    // ДС-1: у клиентов с чётным номером договор продлится сам, у остальных срок вышел и новые КП не создаются
    contract_term:
      client.id % 2 === 0
        ? {
            contract_id: 900 + client.id,
            number: `ДОГ-2026/${String(client.id).padStart(3, "0")}`,
            state: "renews",
            valid_until: "2026-12-31",
            last_notice_date: "2026-12-01",
            foreign: false,
            blocks_new_work: false,
          }
        : {
            contract_id: 900 + client.id,
            number: `ДОГ-2025/${String(client.id).padStart(3, "0")}`,
            state: "expired",
            valid_until: "2025-12-31",
            last_notice_date: "2025-12-01",
            foreign: false,
            blocks_new_work: true,
          },
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

function cardOf(id: string): CounterpartyCard | null {
  const card = baseCardOf(id);
  if (!card) return null;
  return {
    ...card,
    ...requisites.get(id),
    do_not_work: markOf(id),
    // ЕД-5, СУЩ-3: логотип и фото контактов — те же адреса, что отдаёт BFF (версия в `?v=`)
    logo_url: logoUrlOf(id),
    people: card.people.map((person) => ({ ...person, photo_url: photoUrlOf(person.id) })),
  };
}

export const counterpartyHandlers = [
  ...pictureHandlers(cardOf),
  http.patch("*/people/counterparties/:id", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    if (level("crm.clients") !== "full" && level("erp.stock") !== "full") {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff");
    }
    const id = String(params["id"]);
    if (!cardOf(id)) return notFound();
    const body = (await request.json()) as CounterpartyRequisitesIn;
    const taken =
      body.inn && readErpCatalog().suppliers.some((row) => row.id !== id && row.tin === body.inn);
    if (taken) {
      return failure(409, "CONFLICT", "Такая компания уже есть.", "erp", {
        reason: "company_exists",
      });
    }
    const patch: Partial<CounterpartyCard> = {};
    if (body.name !== undefined) patch.name = body.name.trim();
    if (body.inn !== undefined) patch.inn = body.inn;
    if (body.registration_number !== undefined)
      patch.registration_number = body.registration_number;
    if (body.legal_address !== undefined) patch.legal_address = body.legal_address;
    requisites.set(id, { ...requisites.get(id), ...patch });
    return HttpResponse.json(cardOf(id));
  }),
  // Х-8: «Не работать» ставит и снимает тот, кто правит реквизиты (раздел клиентов или каталога — полный)
  http.post("*/people/counterparties/:id/do-not-work", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    if (level("crm.clients") !== "full" && level("erp.stock") !== "full") {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff");
    }
    const id = String(params["id"]);
    const card = cardOf(id);
    if (!card) return notFound();
    const body = (await request.json()) as DoNotWorkIn;
    setMark(id, card.name, {
      reason: body.reason.trim(),
      set_by: currentActor()?.name ?? null,
      set_at: new Date().toISOString(),
      until: body.until ?? null,
    });
    return HttpResponse.json(cardOf(id));
  }),
  http.delete("*/people/counterparties/:id/do-not-work", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    if (level("crm.clients") !== "full" && level("erp.stock") !== "full") {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff");
    }
    const id = String(params["id"]);
    if (!cardOf(id)) return notFound();
    clearMark(id);
    return HttpResponse.json(cardOf(id));
  }),
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
    // не карточка каталога — компания поля выбора (`counterpartyPick.ts`), её роль ставит следующий обработчик
    if (!before) return;
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
