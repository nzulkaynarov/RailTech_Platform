import { HttpResponse, http } from "msw";

import type {
  SupplierCabinetAccess,
  SupplierCabinetContact,
  SupplierCabinetRelationship,
} from "../shared/api/generated/model";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки блока «Доступ в кабинет» карточки поставщика (PART-1, ADR-0022). Права — как в BFF: раздел `erp.stock` (чтение —
 * `read`, изменения — `full`); отказы и коды причин — те же, что у ERP. Состояние держит само: контакты и отношение
 * «партнёр» по поставщику; письмо «уходит» только в виде отметки о приглашении (ссылки и кода в ответах нет).
 */
const ALLOWED = ["my_products", "catalog_requests"] as const;
type Module = (typeof ALLOWED)[number];
const MODULE_SET = new Set<string>(ALLOWED);
const MOCK_NOW = "2026-11-04T10:00:00+05:00";

interface Entry {
  name: string;
  relationship: SupplierCabinetRelationship | null;
  contacts: SupplierCabinetContact[];
  /** Клиентская роль компании (тип CLIENT): роли складываются. */
  client: boolean;
}

function seed(): Record<string, Entry> {
  return {
    "1": {
      name: "ООО «Поставщик Север»",
      relationship: null,
      client: false,
      contacts: [
        {
          id: "501",
          name: "Азиз Тошматов",
          email: "aziz@sever-supply.example",
          phone: "+998 90 000 00 01",
          language: "uz",
          can_act: true,
          invited_at: null,
          last_login_at: null,
        },
      ],
    },
    "2": {
      name: "АО «Южный Металл»",
      client: true,
      relationship: {
        role: "partner",
        kind: "manufacturer",
        modules: ["my_products"],
        catalog_price_visibility: "",
        status: "active",
        invited_at: "2026-10-30T09:00:00+05:00",
        activated_at: "2026-10-30T11:20:00+05:00",
        suspended_at: null,
        responsible: { id: "7", name: "Снабженец Демо" },
        invited_by: { id: "7", name: "Снабженец Демо" },
      },
      contacts: [
        {
          id: "502",
          name: "Малика Юсупова",
          email: "malika@yuzhny-metall.example",
          phone: "",
          language: "ru",
          can_act: true,
          invited_at: "2026-10-30T09:00:00+05:00",
          last_login_at: "2026-11-03T08:15:00+05:00",
        },
      ],
    },
  };
}

let state = seed();
let nextContact = 600;

/** Договорённость о ценах партнёра в каталоге (PART-3) — читает мок номенклатуры для «Цена в каталоге». */
export function partnerPriceVisibility(
  supplierId: string,
): SupplierCabinetRelationship["catalog_price_visibility"] {
  return state[supplierId]?.relationship?.catalog_price_visibility ?? "";
}

export function resetSupplierAccess(): void {
  state = seed();
  nextContact = 600;
}

const failure = (status: number, code: string, message: string, reason?: string, field?: string) =>
  HttpResponse.json(
    {
      code,
      message,
      source: "erp",
      ...(reason ? { details: { reason, ...(field ? { fields: [field] } : {}) } } : {}),
    },
    { status },
  );

interface Caller {
  name: string;
  full: boolean;
}

function guard(need: "read" | "full"): Caller | Response {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const me = buildMe({ ...session, activeRole: null });
  const level = me?.resources["erp.stock"];
  if (!me || !level || (need === "full" && level !== "full")) {
    return HttpResponse.json(
      {
        code: "FORBIDDEN",
        message: "Раздел или действие не положены вашей роли.",
        source: "bff",
        details: { resource: "erp.stock", need },
      },
      { status: 403 },
    );
  }
  return { name: me.name, full: level === "full" };
}

const isResponse = (value: Caller | Response): value is Response => value instanceof Response;

function view(id: string, entry: Entry, canManage = true): SupplierCabinetAccess {
  const relationship = entry.relationship;
  const open = relationship !== null && relationship.status !== "suspended";
  return {
    company_id: id,
    company_name: entry.name,
    relationship,
    contacts: entry.contacts,
    partner_modules: { allowed: [...ALLOWED], default: [...ALLOWED] },
    cabinet_roles: [
      ...(entry.client ? (["client"] as const) : []),
      ...(open ? (["partner"] as const) : []),
    ],
    cabinet_modules: [
      ...(entry.client
        ? [
            "catalog_requests",
            "quotes",
            "documents",
            "contracts",
            "invoices",
            "acts",
            "deliveries",
            "company",
            "team",
            "profile",
          ]
        : []),
      ...(open
        ? relationship.modules.filter((m) => !(entry.client && m === "catalog_requests"))
        : []),
    ],
    can_manage: canManage,
  };
}

const body = async <T>(request: Request): Promise<T> => (await request.json()) as T;
const find = (id: unknown): [string, Entry] | null => {
  const key = String(id);
  const entry = state[key];
  return entry ? [key, entry] : null;
};
const missing = () => failure(404, "NOT_FOUND", "Не найдено");

function cleanModules(value: unknown): Module[] | Response {
  if (!Array.isArray(value) || value.some((m) => typeof m !== "string" || !MODULE_SET.has(m))) {
    return failure(
      422,
      "VALIDATION_FAILED",
      "Проверьте заполнение полей.",
      "module_not_allowed",
      "modules",
    );
  }
  return ALLOWED.filter((m) => value.includes(m));
}

export const erpSupplierAccessHandlers = [
  http.get("*/erp/catalog/suppliers/:id/cabinet-access", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const found = find(params["id"]);
    return found ? HttpResponse.json(view(...found, who.full)) : missing();
  }),
  http.post("*/erp/catalog/suppliers/:id/cabinet-access/contacts", async ({ params, request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const found = find(params["id"]);
    if (!found) return missing();
    const data = await body<{
      name: string;
      email: string;
      phone?: string;
      language?: "ru" | "uz" | "en";
      can_act?: boolean;
    }>(request);
    const email = data.email.trim().toLowerCase();
    if (found[1].contacts.some((c) => c.email.toLowerCase() === email)) {
      return failure(409, "CONFLICT", "Контакт уже есть.", "contact_exists", "email");
    }
    const contact: SupplierCabinetContact = {
      id: String(nextContact++),
      name: data.name.trim(),
      email,
      phone: (data.phone ?? "").trim(),
      language: data.language ?? "ru",
      can_act: data.can_act ?? true,
      invited_at: null,
      last_login_at: null,
    };
    found[1].contacts = [...found[1].contacts, contact];
    return HttpResponse.json(contact, { status: 201 });
  }),
  http.patch(
    "*/erp/catalog/suppliers/:id/cabinet-access/contacts/:contactId",
    async ({ params, request }) => {
      const who = guard("full");
      if (isResponse(who)) return who;
      const found = find(params["id"]);
      const contact = found?.[1].contacts.find((c) => c.id === params["contactId"]);
      if (!found || !contact) return missing();
      const data = await body<Partial<SupplierCabinetContact>>(request);
      Object.assign(contact, {
        ...(data.name !== undefined ? { name: data.name.trim() } : {}),
        ...(data.email !== undefined ? { email: data.email.trim().toLowerCase() } : {}),
        ...(data.phone !== undefined ? { phone: data.phone.trim() } : {}),
        ...(data.language !== undefined ? { language: data.language } : {}),
        ...(data.can_act !== undefined ? { can_act: data.can_act } : {}),
      });
      return HttpResponse.json(contact);
    },
  ),
  http.patch(
    "*/erp/catalog/suppliers/:id/cabinet-access/relationship",
    async ({ params, request }) => {
      const who = guard("full");
      if (isResponse(who)) return who;
      const found = find(params["id"]);
      if (!found || !found[1].relationship) return missing();
      const data = await body<{
        modules?: unknown;
        kind?: SupplierCabinetRelationship["kind"];
        catalog_price_visibility?: SupplierCabinetRelationship["catalog_price_visibility"];
      }>(request);
      if (
        data.catalog_price_visibility !== undefined &&
        !["", "cabinet", "on_request"].includes(data.catalog_price_visibility)
      )
        return failure(
          422,
          "VALIDATION_FAILED",
          "Проверьте заполнение полей.",
          "validation_error",
          "catalog_price_visibility",
        );
      if (data.catalog_price_visibility !== undefined)
        found[1].relationship = {
          ...found[1].relationship,
          catalog_price_visibility: data.catalog_price_visibility,
        };
      if (data.modules !== undefined) {
        const modules = cleanModules(data.modules);
        if (modules instanceof Response) return modules;
        found[1].relationship = { ...found[1].relationship, modules };
      }
      if (data.kind !== undefined)
        found[1].relationship = { ...found[1].relationship, kind: data.kind };
      return HttpResponse.json(view(...found));
    },
  ),
  http.post("*/erp/catalog/suppliers/:id/cabinet-access/invite", async ({ params, request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const found = find(params["id"]);
    if (!found) return missing();
    const data = await body<{
      contact_id: string;
      modules?: unknown;
      kind?: SupplierCabinetRelationship["kind"];
    }>(request);
    const contact = found[1].contacts.find((c) => c.id === data.contact_id);
    if (!contact) return missing();
    const modules = data.modules === undefined ? null : cleanModules(data.modules);
    if (modules instanceof Response) return modules;
    const current = found[1].relationship;
    const person = { id: "7", name: who.name };
    found[1].relationship = {
      role: "partner",
      kind: data.kind ?? current?.kind ?? "",
      modules: modules ?? current?.modules ?? [...ALLOWED],
      catalog_price_visibility: current?.catalog_price_visibility ?? "",
      status: current?.activated_at ? "active" : "invited",
      invited_at: MOCK_NOW,
      activated_at: current?.activated_at ?? null,
      suspended_at: null,
      responsible: current?.responsible ?? person,
      invited_by: person,
    };
    contact.invited_at = MOCK_NOW;
    return HttpResponse.json(view(...found));
  }),
  http.post("*/erp/catalog/suppliers/:id/cabinet-access/suspend", ({ params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const found = find(params["id"]);
    if (!found || !found[1].relationship) return missing();
    found[1].relationship = {
      ...found[1].relationship,
      status: "suspended",
      suspended_at: MOCK_NOW,
    };
    return HttpResponse.json(view(...found));
  }),
];
